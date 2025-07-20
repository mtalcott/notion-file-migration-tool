# Notion to Google Drive Migration Tool

This Python script migrates Notion notes that contain only a single attachment (image or PDF) to Google Drive using the Notion SDK and Google Drive API.

## Features

- Automatically identifies Notion pages with single attachments
- Downloads attachments from Notion
- Uploads files to Google Drive with proper metadata
- Supports images, PDFs, and other file types
- Comprehensive logging and error handling
- Pagination support for large Notion workspaces
- Configurable target folder in Google Drive

## Prerequisites

- Python 3.7 or higher
- Notion integration token
- Google Drive API credentials
- Access to the Notion workspace you want to migrate from

## Installation

1. Clone or download this repository
2. Install the required dependencies:

```bash
pip install -r requirements.txt
```

## Setup

### 1. Notion API Setup

1. Go to [Notion Developers](https://developers.notion.com/)
2. Create a new integration
3. Copy the integration token
4. Share your Notion pages/databases with the integration

### 2. Google Drive API Setup

1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable the Google Drive API
4. Create credentials (OAuth 2.0 Client ID for desktop application)
5. Download the credentials JSON file and save it as `credentials.json` in the project directory

### 3. Environment Configuration

1. Copy the example environment file:
```bash
cp .env.example .env
```

2. Edit the `.env` file with your configuration:

```env
# Notion API Configuration
NOTION_TOKEN=your_notion_integration_token_here
NOTION_DATABASE_ID=your_notion_database_id_here  # Optional: leave empty to search all pages

# Google Drive API Configuration
GOOGLE_CREDENTIALS_FILE=credentials.json
GOOGLE_DRIVE_FOLDER_ID=your_google_drive_folder_id_here  # Optional: leave empty to upload to root
```

#### Getting Notion Database ID (Optional)

If you want to limit the migration to a specific database:
1. Open your Notion database in a web browser
2. Copy the ID from the URL: `https://notion.so/your-workspace/DATABASE_ID?v=...`
3. The DATABASE_ID is the 32-character string between the last `/` and `?`

#### Getting Google Drive Folder ID (Optional)

If you want to upload files to a specific folder:
1. Open the folder in Google Drive
2. Copy the ID from the URL: `https://drive.google.com/drive/folders/FOLDER_ID`
3. The FOLDER_ID is the string after `/folders/`

## Usage

Run the migration script:

```bash
python notion_to_gdrive_migrator.py
```

### First Run

On the first run, the script will:
1. Open a web browser for Google OAuth authentication
2. Ask you to grant permissions to access Google Drive
3. Save the authentication token for future runs

### What the Script Does

1. **Connects to APIs**: Initializes connections to both Notion and Google Drive
2. **Retrieves Pages**: Gets all accessible Notion pages (or from a specific database)
3. **Analyzes Content**: Identifies pages that contain only a single attachment
4. **Downloads Files**: Downloads attachments from Notion
5. **Uploads to Drive**: Uploads files to Google Drive with descriptive metadata
6. **Logs Progress**: Provides detailed logging of the migration process

### Output

The script will:
- Display progress in the console
- Create a `migration.log` file with detailed logs
- Show a summary of migration results at the end

## Configuration Options

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `NOTION_TOKEN` | Yes | Your Notion integration token |
| `NOTION_DATABASE_ID` | No | Specific database ID to migrate from (leave empty for all pages) |
| `GOOGLE_CREDENTIALS_FILE` | No | Path to Google credentials JSON file (default: `credentials.json`) |
| `GOOGLE_DRIVE_FOLDER_ID` | No | Target folder ID in Google Drive (leave empty for root) |

### Supported File Types

The script identifies and migrates:
- Images (PNG, JPG, GIF, etc.)
- PDF files
- Other file attachments

### Single Attachment Detection

A page is considered to have a "single attachment" if:
- It contains exactly one content block
- That block is an image, PDF, or file attachment
- It may contain empty paragraphs, dividers, or unsupported blocks (these are ignored)

## Troubleshooting

### Common Issues

1. **Import Errors**: Make sure all dependencies are installed with `pip install -r requirements.txt`

2. **Notion Authentication**: Ensure your integration token is correct and the integration has access to your pages

3. **Google Drive Authentication**: Make sure your `credentials.json` file is in the correct location and has the right permissions

4. **File Download Errors**: Some Notion file URLs may expire. The script will log these errors and continue with other files.

5. **Permission Errors**: Ensure your Google Drive API credentials have the necessary permissions

### Logs

Check the `migration.log` file for detailed error messages and debugging information.

### Dry Run

To see what would be migrated without actually uploading files, you can modify the script to skip the upload step by commenting out the upload call in the main migration loop.

## Security Notes

- Keep your `.env` file secure and never commit it to version control
- The `credentials.json` and `token.json` files contain sensitive information
- The script only requests minimal necessary permissions for Google Drive

## Limitations

- Only migrates pages with single attachments
- Notion file URLs may have expiration times
- Large files may take longer to download and upload
- Rate limiting may apply for large migrations

## Contributing

Feel free to submit issues, feature requests, or pull requests to improve this tool.

## License

This project is provided as-is for educational and personal use.
