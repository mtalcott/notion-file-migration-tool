#!/usr/bin/env python3
"""
Notion to Google Drive Migration Tool

This script migrates Notion notes that contain only a single attachment 
(image or PDF) to Google Drive using the Notion SDK and Google Drive API.
File timestamps (created and modified dates) are preserved from the original Notion pages.
"""

import os
import logging
import requests
import mimetypes
from datetime import datetime
from typing import List, Dict, Optional, Tuple, Any, cast
from pathlib import Path

from dotenv import load_dotenv
from notion_client import Client as NotionClient
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.exceptions import RefreshError

# Load environment variables
load_dotenv()

# Create timestamped log filename
timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
log_filename = f'migration_{timestamp}.log'

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_filename),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Log which file is being used for logging
logger.info(f"Logging to file: {log_filename}")

# Google Drive API scopes
SCOPES = ['https://www.googleapis.com/auth/drive.file']

class NotionToGDriveMigrator:
    """Main class for migrating Notion attachments to Google Drive."""
    
    def __init__(self):
        """Initialize the migrator with API clients."""
        self.notion_client = self._init_notion_client()
        self.drive_service = self._init_google_drive_service()
        
        # Get and validate database ID
        raw_database_id = os.getenv('NOTION_DATABASE_ID')
        self.notion_database_id = raw_database_id.strip() if raw_database_id else None
        
        # Ensure empty string is treated as None
        if self.notion_database_id == '':
            self.notion_database_id = None
            
        self.gdrive_folder_id = os.getenv('GOOGLE_DRIVE_FOLDER_ID')
        self.database_folder_cache = {}  # Cache for folder paths -> folder ID mapping
        self.uploaded_files = {}  # Track uploaded files for duplicate detection: {filename: file_id}
        self.migrated_pages = []  # Track successfully migrated pages: {title, url, filename}
        
        # Debug logging
        logger.info(f"Raw NOTION_DATABASE_ID from env: '{raw_database_id}'")
        logger.info(f"Processed NOTION_DATABASE_ID: '{self.notion_database_id}'")
        
        if not self.notion_database_id:
            logger.info("NOTION_DATABASE_ID not set. Will search all accessible pages.")
        else:
            logger.info(f"NOTION_DATABASE_ID set to: {self.notion_database_id}")
        
        if not self.gdrive_folder_id:
            logger.warning("GOOGLE_DRIVE_FOLDER_ID not set. Files will be uploaded to root.")
    
    def _init_notion_client(self) -> NotionClient:
        """Initialize Notion client."""
        notion_token = os.getenv('NOTION_TOKEN')
        if not notion_token:
            raise ValueError("NOTION_TOKEN environment variable is required")
        
        # Use the synchronous client explicitly
        return NotionClient(auth=notion_token)
    
    def _init_google_drive_service(self):
        """Initialize Google Drive service."""
        creds = None
        credentials_file = os.getenv('GOOGLE_CREDENTIALS_FILE', 'google_credentials.json')
        token_file = 'token.json'
        
        # Load existing token
        if os.path.exists(token_file):
            creds = Credentials.from_authorized_user_file(token_file, SCOPES)
        
        # If there are no valid credentials, request authorization
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except RefreshError:
                    logger.warning("Token refresh failed, requesting new authorization")
                    creds = None
            
            if not creds:
                if not os.path.exists(credentials_file):
                    raise FileNotFoundError(f"Google credentials file not found: {credentials_file}")
                
                flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
                creds = flow.run_local_server(port=0)
            
            # Save credentials for next run
            with open(token_file, 'w') as token:
                token.write(creds.to_json())
        
        return build('drive', 'v3', credentials=creds)
    
    def get_notion_pages(self) -> List[Dict]:
        """Retrieve pages from Notion."""
        pages = []
        
        try:
            if self.notion_database_id:
                # Query specific database
                logger.info(f"Querying Notion database: {self.notion_database_id}")
                response = cast(Dict[str, Any], self.notion_client.databases.query(
                    database_id=self.notion_database_id
                ))
                pages.extend(response.get('results', []))
                
                # Handle pagination
                while response.get('has_more'):
                    response = cast(Dict[str, Any], self.notion_client.databases.query(
                        database_id=self.notion_database_id,
                        start_cursor=response.get('next_cursor')
                    ))
                    pages.extend(response.get('results', []))
            else:
                # Search all accessible pages
                logger.info("Searching all accessible Notion pages")
                response = cast(Dict[str, Any], self.notion_client.search())
                pages.extend(response.get('results', []))
                
                # Handle pagination
                while response.get('has_more'):
                    response = cast(Dict[str, Any], self.notion_client.search(
                        start_cursor=response.get('next_cursor')
                    ))
                    pages.extend(response.get('results', []))
            
            logger.info(f"Found {len(pages)} pages in Notion")
            return pages
            
        except Exception as e:
            logger.error(f"Error retrieving Notion pages: {e}")
            return []
    
    def get_page_blocks(self, page_id: str) -> List[Dict]:
        """Get all blocks for a specific page."""
        try:
            blocks = []
            response = cast(Dict[str, Any], self.notion_client.blocks.children.list(block_id=page_id))
            blocks.extend(response.get('results', []))
            
            # Handle pagination
            while response.get('has_more'):
                response = cast(Dict[str, Any], self.notion_client.blocks.children.list(
                    block_id=page_id,
                    start_cursor=response.get('next_cursor')
                ))
                blocks.extend(response.get('results', []))
            
            return blocks
            
        except Exception as e:
            logger.error(f"Error retrieving blocks for page {page_id}: {e}")
            return []
    
    def is_single_attachment_page(self, blocks: List[Dict]) -> Tuple[bool, Optional[Dict]]:
        """
        Check if a page contains only a single attachment (image or PDF).
        
        Returns:
            Tuple of (is_single_attachment, attachment_block)
        """
        content_blocks = []
        attachment_block = None
        
        for block in blocks:
            block_type = block.get('type')
            
            # Skip empty blocks
            if block_type in ['paragraph', 'heading_1', 'heading_2', 'heading_3']:
                content = block.get(block_type, {})
                if content.get('rich_text'):
                    # Has text content
                    content_blocks.append(block)
            elif block_type in ['image', 'pdf', 'file']:
                content_blocks.append(block)
                attachment_block = block
            elif block_type not in ['divider', 'unsupported']:
                # Other content types
                content_blocks.append(block)
        
        # Check if there's exactly one content block and it's an attachment
        is_single_attachment = (
            len(content_blocks) == 1 and 
            attachment_block is not None and
            attachment_block['type'] in ['image', 'pdf', 'file']
        )
        
        return is_single_attachment, attachment_block
    
    def get_page_hierarchy(self, page: Dict) -> Dict[str, Any]:
        """
        Get the full hierarchy path for a page (database -> parent pages -> current page).
        
        Returns:
            Dictionary with hierarchy information
        """
        hierarchy = {
            'database_id': None,
            'database_name': None,
            'parent_pages': [],  # List of parent page titles from root to immediate parent
            'full_path': []  # Complete path including database and all parents
        }
        
        try:
            parent = page.get('parent', {})
            parent_type = parent.get('type')
            
            if parent_type == 'database_id':
                # Direct child of database
                hierarchy['database_id'] = parent.get('database_id')
                if hierarchy['database_id']:
                    hierarchy['database_name'] = self.get_database_name(hierarchy['database_id'])
                    hierarchy['full_path'] = [hierarchy['database_name']]
            elif parent_type == 'page_id':
                # Child of another page - need to traverse up the hierarchy
                hierarchy = self._build_page_hierarchy(page, hierarchy)
            
            return hierarchy
            
        except Exception as e:
            logger.warning(f"Error extracting page hierarchy: {e}")
            return hierarchy
    
    def _build_page_hierarchy(self, page: Dict, hierarchy: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively build the page hierarchy by traversing parent pages."""
        try:
            parent = page.get('parent', {})
            parent_type = parent.get('type')
            
            if parent_type == 'page_id':
                parent_page_id = parent.get('page_id')
                if parent_page_id:
                    # Get parent page info
                    parent_page = cast(Dict[str, Any], self.notion_client.pages.retrieve(page_id=parent_page_id))
                    parent_title = self.get_page_title(parent_page)
                    
                    # Add to hierarchy
                    hierarchy['parent_pages'].insert(0, parent_title)
                    
                    # Check if parent has a parent (recursive)
                    parent_hierarchy = self._build_page_hierarchy(parent_page, hierarchy)
                    hierarchy.update(parent_hierarchy)
                    
                    # Update full_path after recursion to include all levels
                    if hierarchy.get('database_name'):
                        hierarchy['full_path'] = [hierarchy['database_name']] + hierarchy['parent_pages']
                    
            elif parent_type == 'block_id':
                # Handle block_id parents - traverse up the block hierarchy
                block_id = parent.get('block_id')
                if block_id:
                    try:
                        # Get the block to find its parent
                        block = cast(Dict[str, Any], self.notion_client.blocks.retrieve(block_id=block_id))
                        block_parent = block.get('parent', {})
                        block_parent_type = block_parent.get('type')
                        
                        if block_parent_type == 'page_id':
                            # Block's parent is a page - get that page and continue hierarchy
                            parent_page_id = block_parent.get('page_id')
                            if parent_page_id:
                                parent_page = cast(Dict[str, Any], self.notion_client.pages.retrieve(page_id=parent_page_id))
                                parent_title = self.get_page_title(parent_page)
                                
                                # Add to hierarchy
                                hierarchy['parent_pages'].insert(0, parent_title)
                                
                                # Continue building hierarchy from the parent page
                                parent_hierarchy = self._build_page_hierarchy(parent_page, hierarchy)
                                hierarchy.update(parent_hierarchy)
                                
                                # Update full_path after recursion
                                if hierarchy.get('database_name'):
                                    hierarchy['full_path'] = [hierarchy['database_name']] + hierarchy['parent_pages']
                                    
                        elif block_parent_type == 'database_id':
                            # Block's parent is a database
                            hierarchy['database_id'] = block_parent.get('database_id')
                            if hierarchy['database_id']:
                                hierarchy['database_name'] = self.get_database_name(hierarchy['database_id'])
                                hierarchy['full_path'] = [hierarchy['database_name']] + hierarchy['parent_pages']
                        elif block_parent_type == 'block_id':
                            # Block's parent is another block - create a fake page object to continue recursion
                            fake_page = {'parent': block_parent}
                            parent_hierarchy = self._build_page_hierarchy(fake_page, hierarchy)
                            hierarchy.update(parent_hierarchy)
                            
                            # Update full_path after recursion
                            if hierarchy.get('database_name'):
                                hierarchy['full_path'] = [hierarchy['database_name']] + hierarchy['parent_pages']
                                
                    except Exception as block_error:
                        logger.warning(f"Error retrieving block {block_id}: {block_error}")
            elif parent_type == 'database_id':
                # Reached the database level
                hierarchy['database_id'] = parent.get('database_id')
                if hierarchy['database_id']:
                    hierarchy['database_name'] = self.get_database_name(hierarchy['database_id'])
                    hierarchy['full_path'] = [hierarchy['database_name']] + hierarchy['parent_pages']
            
            return hierarchy
            
        except Exception as e:
            logger.warning(f"Error building page hierarchy: {e}")
            return hierarchy

    def download_attachment(self, attachment_block: Dict, page_title: str = "") -> Optional[Tuple[str, bytes]]:
        """
        Download attachment from Notion.
        
        Args:
            attachment_block: The attachment block from Notion
            page_title: Title of the page containing the attachment (for better naming)
        
        Returns:
            Tuple of (filename, file_content) or None if failed
        """
        try:
            block_type = attachment_block['type']
            attachment_data = attachment_block[block_type]
            
            # Get file URL and name
            file_url = None
            filename = None
            
            if attachment_data.get('type') == 'external':
                file_url = attachment_data['external']['url']
                # Safely get caption
                caption_array = attachment_data.get('caption', [])
                if caption_array and len(caption_array) > 0:
                    filename = caption_array[0].get('plain_text', '')
            elif attachment_data.get('type') == 'file':
                file_url = attachment_data['file']['url']
                # Safely get caption
                caption_array = attachment_data.get('caption', [])
                if caption_array and len(caption_array) > 0:
                    filename = caption_array[0].get('plain_text', '')
            else:
                logger.warning(f"Unsupported attachment type: {attachment_data.get('type')}")
                return None
            
            if not file_url:
                logger.error("No file URL found in attachment")
                return None
            
            # Extract filename from URL if not provided or empty
            if not filename or filename.strip() == '':
                filename = os.path.basename(file_url.split('?')[0])
                # If still no filename, create a default one
                if not filename or filename.strip() == '':
                    filename = f"attachment_{attachment_block.get('id', 'unknown')}"
            
            # Always use page title as filename when available
            if page_title and page_title.strip():
                # Determine the appropriate file extension
                original_extension = Path(filename).suffix
                if not original_extension and block_type in ['image', 'pdf']:
                    if block_type == 'image':
                        original_extension = '.png'
                    elif block_type == 'pdf':
                        original_extension = '.pdf'
                
                # Sanitize page title for filename
                safe_page_title = "".join(c for c in page_title if c.isalnum() or c in (' ', '-', '_')).strip()
                if safe_page_title:
                    filename = safe_page_title + original_extension
                    logger.info(f"Using page title as filename: {filename}")
            
            # Ensure filename has proper extension
            if not Path(filename).suffix and block_type in ['image', 'pdf']:
                if block_type == 'image':
                    filename += '.png'  # Default for images
                elif block_type == 'pdf':
                    filename += '.pdf'
            
            # Final sanitization for filesystem
            filename = "".join(c for c in filename if c.isalnum() or c in (' ', '-', '_', '.')).strip()
            if not filename:
                filename = f"attachment_{attachment_block.get('id', 'unknown')}"
            
            # Download file
            logger.info(f"Downloading attachment: {filename}")
            logger.debug(f"File URL: {file_url}")
            response = requests.get(file_url, timeout=30)
            response.raise_for_status()
            
            return filename, response.content
            
        except Exception as e:
            logger.error(f"Error downloading attachment: {e}")
            logger.debug(f"Attachment block structure: {attachment_block}")
            return None
    
    def check_for_duplicate(self, filename: str, target_folder_id: Optional[str] = None) -> Optional[str]:
        """
        Check if a file with the same name already exists in the target folder.
        
        Args:
            filename: Name of the file to check
            target_folder_id: Folder ID to check in (None for root)
            
        Returns:
            File ID if duplicate exists, None otherwise
        """
        try:
            folder_id = target_folder_id or self.gdrive_folder_id or 'root'
            
            # Search for files with the same name in the target folder
            query = f"name='{filename}' and '{folder_id}' in parents and trashed=false"
            results = self.drive_service.files().list(  # type: ignore
                q=query, 
                fields='files(id, name, createdTime)'
            ).execute()
            
            existing_files = results.get('files', [])
            if existing_files:
                existing_file = existing_files[0]  # Get the first match
                logger.info(f"Duplicate found: {filename} (ID: {existing_file['id']}, Created: {existing_file.get('createdTime', 'Unknown')})")
                return existing_file['id']
            
            return None
            
        except Exception as e:
            logger.warning(f"Error checking for duplicate {filename}: {e}")
            return None

    def upload_to_google_drive(self, filename: str, file_content: bytes, page_title: str, page: Dict, target_folder_id: Optional[str] = None) -> Optional[str]:
        """
        Upload file to Google Drive with duplicate detection and Notion timestamps.
        
        Args:
            filename: Name of the file to upload
            file_content: Binary content of the file
            page_title: Title of the Notion page (for metadata)
            page: The Notion page object containing timestamp information
            target_folder_id: Specific folder ID to upload to (overrides default)
        
        Returns:
            File ID if successful, None otherwise
        """
        try:
            # Check for duplicates first
            existing_file_id = self.check_for_duplicate(filename, target_folder_id)
            if existing_file_id:
                logger.info(f"Skipping upload - duplicate file already exists: {filename}")
                return existing_file_id
            
            # Create a temporary file
            temp_file_path = f"/tmp/{filename}"
            with open(temp_file_path, 'wb') as temp_file:
                temp_file.write(file_content)
            
            # Determine MIME type
            mime_type, _ = mimetypes.guess_type(filename)
            if not mime_type:
                mime_type = 'application/octet-stream'
            
            # Prepare file metadata with Notion timestamps
            file_metadata: Dict[str, Any] = {
                'name': filename,
                'description': f'Migrated from Notion page: {page_title}'
            }
            
            # Set timestamps based on Notion page dates
            created_time = page.get('created_time')
            last_edited_time = page.get('last_edited_time')
            
            if created_time:
                file_metadata['createdTime'] = created_time
                logger.debug(f"Setting created time to: {created_time}")
            
            if last_edited_time:
                file_metadata['modifiedTime'] = last_edited_time
                logger.debug(f"Setting modified time to: {last_edited_time}")
            
            # Determine target folder
            folder_id = target_folder_id or self.gdrive_folder_id
            if folder_id:
                file_metadata['parents'] = [folder_id]
            
            # Upload file
            media = MediaFileUpload(temp_file_path, mimetype=mime_type)
            file = self.drive_service.files().create(  # type: ignore
                body=file_metadata,
                media_body=media,
                fields='id,name,webViewLink'
            ).execute()
            
            # Clean up temporary file
            os.remove(temp_file_path)
            
            # Track uploaded file for future duplicate detection
            file_id = file.get('id')
            self.uploaded_files[filename] = file_id
            
            logger.info(f"Successfully uploaded {filename} to Google Drive (ID: {file_id})")
            return file_id
            
        except Exception as e:
            logger.error(f"Error uploading {filename} to Google Drive: {e}")
            # Clean up temporary file if it exists
            temp_file_path = f"/tmp/{filename}"
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)
            return None
    
    def get_database_name(self, database_id: str) -> str:
        """Get the name of a Notion database."""
        try:
            database = cast(Dict[str, Any], self.notion_client.databases.retrieve(database_id=database_id))
            title_array = database.get('title', [])
            if title_array:
                return ''.join([t.get('plain_text', '') for t in title_array])
            return f"Untitled Database ({database_id})"
        except Exception as e:
            logger.warning(f"Error retrieving database name for {database_id}: {e}")
            return f"Unknown Database ({database_id})"
    
    def create_hierarchical_folders(self, hierarchy: Dict[str, Any]) -> Optional[str]:
        """
        Create or get the full folder hierarchy in Google Drive based on page hierarchy.
        
        Args:
            hierarchy: Dictionary containing the page hierarchy information
            
        Returns:
            Final folder ID if successful, None otherwise
        """
        try:
            full_path = hierarchy.get('full_path', [])
            if not full_path:
                return self.gdrive_folder_id
            
            # Start from the root folder
            current_folder_id = self.gdrive_folder_id or 'root'
            
            # Create each folder in the hierarchy
            for folder_name in full_path:
                current_folder_id = self._create_or_get_folder(folder_name, current_folder_id)
                if not current_folder_id:
                    logger.error(f"Failed to create/get folder: {folder_name}")
                    return None
            
            return current_folder_id
            
        except Exception as e:
            logger.error(f"Error creating hierarchical folders: {e}")
            return None
    
    def _create_or_get_folder(self, folder_name: str, parent_folder_id: str) -> Optional[str]:
        """
        Create or get a specific folder in Google Drive.
        
        Args:
            folder_name: Name of the folder to create/get
            parent_folder_id: ID of the parent folder
            
        Returns:
            Folder ID if successful, None otherwise
        """
        try:
            # Sanitize folder name for Google Drive
            safe_folder_name = "".join(c for c in folder_name if c.isalnum() or c in (' ', '-', '_', '.')).strip()
            if not safe_folder_name:
                safe_folder_name = "Untitled_Folder"
            
            # Create cache key for this specific folder path
            cache_key = f"{parent_folder_id}:{safe_folder_name}"
            if cache_key in self.database_folder_cache:
                return self.database_folder_cache[cache_key]
            
            # Check if folder already exists
            query = f"name='{safe_folder_name}' and '{parent_folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
            results = self.drive_service.files().list(q=query, fields='files(id, name)').execute()
            existing_folders = results.get('files', [])
            
            if existing_folders:
                # Folder already exists
                folder_id = existing_folders[0]['id']
                logger.debug(f"Using existing folder '{safe_folder_name}' (ID: {folder_id})")
            else:
                # Create new folder
                folder_metadata = {
                    'name': safe_folder_name,
                    'mimeType': 'application/vnd.google-apps.folder',
                    'parents': [parent_folder_id]
                }
                
                folder = self.drive_service.files().create(
                    body=folder_metadata,
                    fields='id,name'
                ).execute()
                
                folder_id = folder.get('id')
                logger.info(f"Created new folder '{safe_folder_name}' (ID: {folder_id})")
            
            # Cache the result
            self.database_folder_cache[cache_key] = folder_id
            return folder_id
            
        except Exception as e:
            logger.error(f"Error creating/getting folder '{folder_name}': {e}")
            return None

    def create_or_get_database_folder(self, database_id: str) -> Optional[str]:
        """
        Create or get a subfolder in Google Drive based on the database name.
        This method is kept for backward compatibility.
        
        Returns:
            Folder ID if successful, None otherwise
        """
        # Check cache first
        if database_id in self.database_folder_cache:
            return self.database_folder_cache[database_id]
        
        try:
            # Get database name
            database_name = self.get_database_name(database_id)
            
            # Use the new hierarchical folder creation
            hierarchy = {
                'full_path': [database_name]
            }
            
            return self.create_hierarchical_folders(hierarchy)
            
        except Exception as e:
            logger.error(f"Error creating/getting database folder for {database_id}: {e}")
            return None

    def get_page_database_id(self, page: Dict) -> Optional[str]:
        """Extract the database ID from a page if it belongs to a database."""
        try:
            hierarchy = self.get_page_hierarchy(page)
            return hierarchy.get('database_id')
        except Exception as e:
            logger.warning(f"Error extracting database ID from page: {e}")
            return None
    
    def get_page_title(self, page: Dict) -> str:
        """Extract page title from Notion page object."""
        try:
            properties = page.get('properties', {})
            
            # Look for title property
            for prop_name, prop_data in properties.items():
                if prop_data.get('type') == 'title':
                    title_array = prop_data.get('title', [])
                    if title_array:
                        return ''.join([t.get('plain_text', '') for t in title_array])
            
            # Fallback to page object title
            if 'title' in page:
                title_array = page.get('title', [])
                if title_array:
                    return ''.join([t.get('plain_text', '') for t in title_array])
            
            return f"Untitled Page ({page.get('id', 'unknown')})"
            
        except Exception as e:
            logger.warning(f"Error extracting page title: {e}")
            return f"Untitled Page ({page.get('id', 'unknown')})"
    
    def get_notion_page_url(self, page_id: str) -> str:
        """Generate the Notion page URL from page ID."""
        # Remove hyphens from page ID for URL
        clean_page_id = page_id.replace('-', '')
        return f"https://www.notion.so/{clean_page_id}"
    
    def migrate_single_attachment_pages(self) -> Dict[str, int]:
        """
        Main migration function.
        
        Returns:
            Dictionary with migration statistics
        """
        stats = {
            'total_pages': 0,
            'single_attachment_pages': 0,
            'successful_migrations': 0,
            'failed_migrations': 0
        }
        
        logger.info("Starting Notion to Google Drive migration...")
        logger.info("NOTE: This is a COPY operation - no files will be deleted from Notion")
        
        # Get all pages
        pages = self.get_notion_pages()
        stats['total_pages'] = len(pages)
        
        if not pages:
            logger.warning("No pages found in Notion")
            return stats
        
        # Process each page
        for page in pages:
            page_id = page['id']
            page_title = self.get_page_title(page)
            
            logger.info(f"Processing page: {page_title}")
            
            # Log page timestamps for debugging
            created_time = page.get('created_time')
            last_edited_time = page.get('last_edited_time')
            if created_time:
                logger.debug(f"Page created: {created_time}")
            if last_edited_time:
                logger.debug(f"Page last edited: {last_edited_time}")
            
            # Get page blocks
            blocks = self.get_page_blocks(page_id)
            
            # Check if it's a single attachment page
            is_single_attachment, attachment_block = self.is_single_attachment_page(blocks)
            
            if is_single_attachment and attachment_block is not None:
                stats['single_attachment_pages'] += 1
                logger.info(f"Found single attachment page: {page_title}")
                
                # Get full hierarchy for this page
                hierarchy = self.get_page_hierarchy(page)
                
                # Debug logging for hierarchy
                logger.debug(f"Page hierarchy for '{page_title}':")
                logger.debug(f"  Database ID: {hierarchy.get('database_id')}")
                logger.debug(f"  Database Name: {hierarchy.get('database_name')}")
                logger.debug(f"  Parent Pages: {hierarchy.get('parent_pages')}")
                logger.debug(f"  Full Path: {hierarchy.get('full_path')}")
                
                # Determine target folder based on hierarchy
                target_folder_id = None
                if hierarchy.get('full_path'):
                    target_folder_id = self.create_hierarchical_folders(hierarchy)
                    if target_folder_id:
                        folder_path = ' > '.join(hierarchy['full_path'])
                        logger.info(f"Will upload to hierarchical folder: {folder_path}")
                elif hierarchy.get('database_id'):
                    # Fallback to simple database folder
                    target_folder_id = self.create_or_get_database_folder(hierarchy['database_id'])
                    if target_folder_id:
                        database_name = self.get_database_name(hierarchy['database_id'])
                        logger.info(f"Will upload to database folder: {database_name}")
                
                # Download attachment with improved filename handling
                download_result = self.download_attachment(attachment_block, page_title)
                if download_result:
                    filename, file_content = download_result
                    
                    # Upload to Google Drive (to hierarchical folder if available)
                    file_id = self.upload_to_google_drive(filename, file_content, page_title, page, target_folder_id)
                    if file_id:
                        stats['successful_migrations'] += 1
                        page_url = self.get_notion_page_url(page_id)
                        logger.info(f"Successfully migrated: {page_title} -> {filename} | Notion URL: {page_url}")
                        
                        # Track migrated page
                        self.migrated_pages.append({
                            'title': page_title,
                            'url': page_url,
                            'filename': filename
                        })
                    else:
                        stats['failed_migrations'] += 1
                        logger.error(f"Failed to upload: {page_title}")
                else:
                    stats['failed_migrations'] += 1
                    logger.error(f"Failed to download attachment from: {page_title}")
            else:
                logger.debug(f"Skipping page (not single attachment): {page_title}")
        
        # Log final statistics
        logger.info("Migration completed!")
        logger.info(f"Total pages processed: {stats['total_pages']}")
        logger.info(f"Single attachment pages found: {stats['single_attachment_pages']}")
        logger.info(f"Successful migrations: {stats['successful_migrations']}")
        logger.info(f"Failed migrations: {stats['failed_migrations']}")
        
        # Log all successfully migrated pages with URLs
        if self.migrated_pages:
            logger.info("\n" + "="*60)
            logger.info("SUCCESSFULLY MIGRATED NOTION PAGES:")
            logger.info("="*60)
            for i, page_info in enumerate(self.migrated_pages, 1):
                logger.info(f"{i}. {page_info['title']}")
                logger.info(f"   Filename: {page_info['filename']}")
                logger.info(f"   Notion URL: {page_info['url']}")
                logger.info("")
            logger.info("="*60)
        
        return stats


def main():
    """Main function to run the migration."""
    try:
        migrator = NotionToGDriveMigrator()
        stats = migrator.migrate_single_attachment_pages()
        
        print("\n" + "="*50)
        print("MIGRATION SUMMARY")
        print("="*50)
        print(f"Total pages processed: {stats['total_pages']}")
        print(f"Single attachment pages found: {stats['single_attachment_pages']}")
        print(f"Successful migrations: {stats['successful_migrations']}")
        print(f"Failed migrations: {stats['failed_migrations']}")
        print("="*50)
        print("\nNOTE: This was a COPY operation - no files were deleted from Notion")
        print("File timestamps (created/modified dates) are preserved from Notion pages")
        
        if stats['failed_migrations'] > 0:
            print(f"\nSome migrations failed. Check {log_filename} for details.")
        
    except Exception as e:
        logger.error(f"Migration failed with error: {e}")
        print(f"Error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
