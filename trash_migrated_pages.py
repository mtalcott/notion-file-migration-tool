#!/usr/bin/env python3
"""
Notion Page Trash Script

This script parses a migration log file and moves all successfully migrated 
Notion pages to the trash. It extracts Notion URLs from the log and uses 
the Notion API to delete the corresponding pages.
"""

import os
import re
import logging
import argparse
from datetime import datetime
from typing import List, Dict, Optional
from urllib.parse import urlparse

from dotenv import load_dotenv
from notion_client import Client as NotionClient

# Load environment variables
load_dotenv()

# Create timestamped log filename for this script
timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
trash_log_filename = f'trash_pages_{timestamp}.log'

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(trash_log_filename),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class NotionPageTrasher:
    """Class for moving migrated Notion pages to trash."""
    
    def __init__(self):
        """Initialize the trasher with Notion client."""
        self.notion_client = self._init_notion_client()
        self.trashed_pages = []  # Track successfully trashed pages
        self.failed_pages = []   # Track pages that failed to trash
    
    def _init_notion_client(self) -> NotionClient:
        """Initialize Notion client."""
        notion_token = os.getenv('NOTION_TOKEN')
        if not notion_token:
            raise ValueError("NOTION_TOKEN environment variable is required")
        
        return NotionClient(auth=notion_token)
    
    def extract_notion_urls_from_log(self, log_file_path: str) -> List[Dict[str, str]]:
        """
        Extract Notion URLs and page titles from migration log file.
        
        Args:
            log_file_path: Path to the migration log file
            
        Returns:
            List of dictionaries containing page info
        """
        migrated_pages = []
        
        try:
            with open(log_file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Pattern to match successful migration log entries
            # Example: "Successfully migrated: Page Title -> filename.pdf | Notion URL: https://www.notion.so/..."
            pattern = r'Successfully migrated: (.+?) -> (.+?) \| Notion URL: (https://www\.notion\.so/[a-f0-9]+)'
            
            matches = re.findall(pattern, content)
            
            for match in matches:
                page_title = match[0].strip()
                filename = match[1].strip()
                notion_url = match[2].strip()
                
                # Extract page ID from URL
                page_id = self._extract_page_id_from_url(notion_url)
                if page_id:
                    migrated_pages.append({
                        'title': page_title,
                        'filename': filename,
                        'url': notion_url,
                        'page_id': page_id
                    })
                    logger.debug(f"Found migrated page: {page_title} (ID: {page_id})")
                else:
                    logger.warning(f"Could not extract page ID from URL: {notion_url}")
            
            logger.info(f"Found {len(migrated_pages)} successfully migrated pages in log file")
            return migrated_pages
            
        except FileNotFoundError:
            logger.error(f"Log file not found: {log_file_path}")
            return []
        except Exception as e:
            logger.error(f"Error reading log file {log_file_path}: {e}")
            return []
    
    def _extract_page_id_from_url(self, notion_url: str) -> Optional[str]:
        """
        Extract page ID from Notion URL.
        
        Args:
            notion_url: Notion page URL
            
        Returns:
            Page ID with hyphens added back, or None if extraction fails
        """
        try:
            # Parse URL to get the path
            parsed = urlparse(notion_url)
            path = parsed.path.strip('/')
            
            # Extract the page ID (32 character hex string)
            if len(path) >= 32:
                # Take the last 32 characters as the page ID
                page_id_clean = path[-32:]
                
                # Add hyphens back to make it a proper UUID format
                page_id = f"{page_id_clean[:8]}-{page_id_clean[8:12]}-{page_id_clean[12:16]}-{page_id_clean[16:20]}-{page_id_clean[20:32]}"
                
                return page_id
            
            return None
            
        except Exception as e:
            logger.warning(f"Error extracting page ID from URL {notion_url}: {e}")
            return None
    
    def trash_page(self, page_info: Dict[str, str]) -> bool:
        """
        Move a single page to trash.
        
        Args:
            page_info: Dictionary containing page information
            
        Returns:
            True if successful, False otherwise
        """
        try:
            page_id = page_info['page_id']
            page_title = page_info['title']
            
            # Archive (trash) the page
            self.notion_client.pages.update(
                page_id=page_id,
                archived=True
            )
            
            logger.info(f"Successfully trashed page: {page_title} (ID: {page_id})")
            self.trashed_pages.append(page_info)
            return True
            
        except Exception as e:
            logger.error(f"Failed to trash page '{page_info['title']}' (ID: {page_info['page_id']}): {e}")
            self.failed_pages.append(page_info)
            return False
    
    def trash_migrated_pages(self, log_file_path: str, dry_run: bool = False) -> Dict[str, int]:
        """
        Main function to trash all migrated pages from log file.
        
        Args:
            log_file_path: Path to the migration log file
            dry_run: If True, only show what would be trashed without actually doing it
            
        Returns:
            Dictionary with statistics
        """
        stats = {
            'total_found': 0,
            'successfully_trashed': 0,
            'failed_to_trash': 0
        }
        
        logger.info(f"Starting to process migration log: {log_file_path}")
        if dry_run:
            logger.info("DRY RUN MODE - No pages will actually be trashed")
        
        # Extract migrated pages from log
        migrated_pages = self.extract_notion_urls_from_log(log_file_path)
        stats['total_found'] = len(migrated_pages)
        
        if not migrated_pages:
            logger.warning("No migrated pages found in log file")
            return stats
        
        # Process each page
        for page_info in migrated_pages:
            if dry_run:
                logger.info(f"[DRY RUN] Would trash: {page_info['title']} (ID: {page_info['page_id']})")
                stats['successfully_trashed'] += 1
            else:
                if self.trash_page(page_info):
                    stats['successfully_trashed'] += 1
                else:
                    stats['failed_to_trash'] += 1
        
        # Log final statistics
        logger.info("Trash operation completed!")
        logger.info(f"Total pages found in log: {stats['total_found']}")
        logger.info(f"Successfully trashed: {stats['successfully_trashed']}")
        logger.info(f"Failed to trash: {stats['failed_to_trash']}")
        
        # Log detailed results
        if self.trashed_pages:
            logger.info("\n" + "="*60)
            logger.info("SUCCESSFULLY TRASHED PAGES:")
            logger.info("="*60)
            for i, page_info in enumerate(self.trashed_pages, 1):
                logger.info(f"{i}. {page_info['title']}")
                logger.info(f"   Original filename: {page_info['filename']}")
                logger.info(f"   Page ID: {page_info['page_id']}")
                logger.info("")
            logger.info("="*60)
        
        if self.failed_pages:
            logger.warning("\n" + "="*60)
            logger.warning("FAILED TO TRASH PAGES:")
            logger.warning("="*60)
            for i, page_info in enumerate(self.failed_pages, 1):
                logger.warning(f"{i}. {page_info['title']}")
                logger.warning(f"   Page ID: {page_info['page_id']}")
                logger.warning(f"   URL: {page_info['url']}")
                logger.warning("")
            logger.warning("="*60)
        
        return stats


def main():
    """Main function to run the trash script."""
    parser = argparse.ArgumentParser(
        description="Move successfully migrated Notion pages to trash based on migration log file"
    )
    parser.add_argument(
        'log_file',
        help='Path to the migration log file'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be trashed without actually doing it'
    )
    
    args = parser.parse_args()
    
    try:
        trasher = NotionPageTrasher()
        stats = trasher.trash_migrated_pages(args.log_file, dry_run=args.dry_run)
        
        print("\n" + "="*50)
        print("TRASH OPERATION SUMMARY")
        print("="*50)
        print(f"Total pages found in log: {stats['total_found']}")
        print(f"Successfully trashed: {stats['successfully_trashed']}")
        print(f"Failed to trash: {stats['failed_to_trash']}")
        print("="*50)
        
        if args.dry_run:
            print("\nThis was a DRY RUN - no pages were actually trashed")
            print("Run without --dry-run to actually move pages to trash")
        else:
            print(f"\nDetailed log saved to: {trash_log_filename}")
        
        if stats['failed_to_trash'] > 0:
            print(f"\nSome pages failed to trash. Check {trash_log_filename} for details.")
            return 1
        
        return 0
        
    except Exception as e:
        logger.error(f"Trash operation failed with error: {e}")
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    exit(main())
