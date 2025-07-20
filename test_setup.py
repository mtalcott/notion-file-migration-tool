#!/usr/bin/env python3
"""
Test script to verify the setup for the Notion to Google Drive migration tool.
"""

import os
import sys
from dotenv import load_dotenv

def test_dependencies():
    """Test if all required dependencies are installed."""
    print("Testing dependencies...")
    
    try:
        import notion_client
        print("✓ notion-client installed")
    except ImportError:
        print("✗ notion-client not installed")
        return False
    
    try:
        import googleapiclient
        print("✓ google-api-python-client installed")
    except ImportError:
        print("✗ google-api-python-client not installed")
        return False
    
    try:
        import google.auth
        print("✓ google-auth installed")
    except ImportError:
        print("✗ google-auth not installed")
        return False
    
    try:
        import requests
        print("✓ requests installed")
    except ImportError:
        print("✗ requests not installed")
        return False
    
    return True

def test_environment():
    """Test if environment variables are configured."""
    print("\nTesting environment configuration...")
    
    load_dotenv()
    
    notion_token = os.getenv('NOTION_TOKEN')
    if notion_token:
        print("✓ NOTION_TOKEN is set")
    else:
        print("✗ NOTION_TOKEN is not set")
        return False
    
    credentials_file = os.getenv('GOOGLE_CREDENTIALS_FILE', 'credentials.json')
    if os.path.exists(credentials_file):
        print(f"✓ Google credentials file found: {credentials_file}")
    else:
        print(f"✗ Google credentials file not found: {credentials_file}")
        return False
    
    database_id = os.getenv('NOTION_DATABASE_ID')
    if database_id:
        print(f"✓ NOTION_DATABASE_ID is set (will query specific database)")
    else:
        print("ℹ NOTION_DATABASE_ID not set (will search all accessible pages)")
    
    folder_id = os.getenv('GOOGLE_DRIVE_FOLDER_ID')
    if folder_id:
        print(f"✓ GOOGLE_DRIVE_FOLDER_ID is set (will upload to specific folder)")
    else:
        print("ℹ GOOGLE_DRIVE_FOLDER_ID not set (will upload to root)")
    
    return True

def test_notion_connection():
    """Test connection to Notion API."""
    print("\nTesting Notion API connection...")
    
    try:
        from notion_client import Client as NotionClient
        
        notion_token = os.getenv('NOTION_TOKEN')
        if not notion_token:
            print("✗ Cannot test Notion connection: NOTION_TOKEN not set")
            return False
        
        client = NotionClient(auth=notion_token)
        
        # Try to list users (minimal API call)
        response = client.users.list()
        print("✓ Notion API connection successful")
        return True
        
    except Exception as e:
        print(f"✗ Notion API connection failed: {e}")
        return False

def main():
    """Run all tests."""
    print("Notion to Google Drive Migration Tool - Setup Test")
    print("=" * 50)
    
    all_passed = True
    
    # Test dependencies
    if not test_dependencies():
        all_passed = False
        print("\n❌ Some dependencies are missing. Run: pip install -r requirements.txt")
    
    # Test environment
    if not test_environment():
        all_passed = False
        print("\n❌ Environment configuration incomplete. Check your .env file and credentials.json")
    
    # Test Notion connection
    if not test_notion_connection():
        all_passed = False
        print("\n❌ Notion API connection failed. Check your NOTION_TOKEN")
    
    print("\n" + "=" * 50)
    if all_passed:
        print("🎉 All tests passed! You're ready to run the migration.")
        print("Run: python notion_to_gdrive_migrator.py")
    else:
        print("❌ Some tests failed. Please fix the issues above before running the migration.")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())
