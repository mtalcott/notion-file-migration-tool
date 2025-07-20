#!/usr/bin/env python3
"""
Notion to Google Drive Migration Tool

This script migrates Notion notes that contain only a single attachment 
(image or PDF) to Google Drive using the Notion SDK and Google Drive API.
"""

import os
import logging
import requests
import mimetypes
from typing import List, Dict, Optional, Tuple, Any
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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('migration.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Google Drive API scopes
SCOPES = ['https://www.googleapis.com/auth/drive.file']

class NotionToGDriveMigrator:
    """Main class for migrating Notion attachments to Google Drive."""
    
    def __init__(self):
        """Initialize the migrator with API clients."""
        self.notion_client = self._init_notion_client()
        self.drive_service = self._init_google_drive_service()
        self.notion_database_id = os.getenv('NOTION_DATABASE_ID')
        self.gdrive_folder_id = os.getenv('GOOGLE_DRIVE_FOLDER_ID')
        
        if not self.notion_database_id:
            logger.warning("NOTION_DATABASE_ID not set. Will search all accessible pages.")
        
        if not self.gdrive_folder_id:
            logger.warning("GOOGLE_DRIVE_FOLDER_ID not set. Files will be uploaded to root.")
    
    def _init_notion_client(self) -> NotionClient:
        """Initialize Notion client."""
        notion_token = os.getenv('NOTION_TOKEN')
        if not notion_token:
            raise ValueError("NOTION_TOKEN environment variable is required")
        
        return NotionClient(auth=notion_token)
    
    def _init_google_drive_service(self):
        """Initialize Google Drive service."""
        creds = None
        credentials_file = os.getenv('GOOGLE_CREDENTIALS_FILE', 'credentials.json')
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
                response = self.notion_client.databases.query(
                    database_id=self.notion_database_id
                )
                pages.extend(response.get('results', []))
                
                # Handle pagination
                while response.get('has_more'):
                    response = self.notion_client.databases.query(
                        database_id=self.notion_database_id,
                        start_cursor=response.get('next_cursor')
                    )
                    pages.extend(response.get('results', []))
            else:
                # Search all accessible pages
                logger.info("Searching all accessible Notion pages")
                response = self.notion_client.search()
                pages.extend(response.get('results', []))
                
                # Handle pagination
                while response.get('has_more'):
                    response = self.notion_client.search(
                        start_cursor=response.get('next_cursor')
                    )
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
            response = self.notion_client.blocks.children.list(block_id=page_id)
            blocks.extend(response.get('results', []))
            
            # Handle pagination
            while response.get('has_more'):
                response = self.notion_client.blocks.children.list(
                    block_id=page_id,
                    start_cursor=response.get('next_cursor')
                )
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
    
    def download_attachment(self, attachment_block: Dict) -> Optional[Tuple[str, bytes]]:
        """
        Download attachment from Notion.
        
        Returns:
            Tuple of (filename, file_content) or None if failed
        """
        try:
            block_type = attachment_block['type']
            attachment_data = attachment_block[block_type]
            
            # Get file URL and name
            if attachment_data.get('type') == 'external':
                file_url = attachment_data['external']['url']
                filename = attachment_data.get('caption', [{}])[0].get('plain_text', 'attachment')
            elif attachment_data.get('type') == 'file':
                file_url = attachment_data['file']['url']
                filename = attachment_data.get('caption', [{}])[0].get('plain_text', 'attachment')
            else:
                logger.warning(f"Unsupported attachment type: {attachment_data.get('type')}")
                return None
            
            # Extract filename from URL if not provided
            if not filename or filename == 'attachment':
                filename = os.path.basename(file_url.split('?')[0])
            
            # Ensure filename has proper extension
            if not Path(filename).suffix and block_type in ['image', 'pdf']:
                if block_type == 'image':
                    filename += '.png'  # Default for images
                elif block_type == 'pdf':
                    filename += '.pdf'
            
            # Download file
            logger.info(f"Downloading attachment: {filename}")
            response = requests.get(file_url, timeout=30)
            response.raise_for_status()
            
            return filename, response.content
            
        except Exception as e:
            logger.error(f"Error downloading attachment: {e}")
            return None
    
    def upload_to_google_drive(self, filename: str, file_content: bytes, page_title: str) -> Optional[str]:
        """
        Upload file to Google Drive.
        
        Returns:
            File ID if successful, None otherwise
        """
        try:
            # Create a temporary file
            temp_file_path = f"/tmp/{filename}"
            with open(temp_file_path, 'wb') as temp_file:
                temp_file.write(file_content)
            
            # Determine MIME type
            mime_type, _ = mimetypes.guess_type(filename)
            if not mime_type:
                mime_type = 'application/octet-stream'
            
            # Prepare file metadata
            file_metadata: Dict[str, Any] = {
                'name': filename,
                'description': f'Migrated from Notion page: {page_title}'
            }
            
            # Add to specific folder if specified
            if self.gdrive_folder_id:
                file_metadata['parents'] = [self.gdrive_folder_id]
            
            # Upload file
            media = MediaFileUpload(temp_file_path, mimetype=mime_type)
            file = self.drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id,name,webViewLink'
            ).execute()
            
            # Clean up temporary file
            os.remove(temp_file_path)
            
            logger.info(f"Successfully uploaded {filename} to Google Drive (ID: {file.get('id')})")
            return file.get('id')
            
        except Exception as e:
            logger.error(f"Error uploading {filename} to Google Drive: {e}")
            # Clean up temporary file if it exists
            temp_file_path = f"/tmp/{filename}"
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)
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
            
            # Get page blocks
            blocks = self.get_page_blocks(page_id)
            
            # Check if it's a single attachment page
            is_single_attachment, attachment_block = self.is_single_attachment_page(blocks)
            
            if is_single_attachment and attachment_block is not None:
                stats['single_attachment_pages'] += 1
                logger.info(f"Found single attachment page: {page_title}")
                
                # Download attachment
                download_result = self.download_attachment(attachment_block)
                if download_result:
                    filename, file_content = download_result
                    
                    # Upload to Google Drive
                    file_id = self.upload_to_google_drive(filename, file_content, page_title)
                    if file_id:
                        stats['successful_migrations'] += 1
                        logger.info(f"Successfully migrated: {page_title} -> {filename}")
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
        
        if stats['failed_migrations'] > 0:
            print("\nSome migrations failed. Check migration.log for details.")
        
    except Exception as e:
        logger.error(f"Migration failed with error: {e}")
        print(f"Error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
