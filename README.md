# Notion to Google Drive Attachment Migrator

This Python toolkit migrates Notion notes that contain only a single attachment (image or PDF) to Google Drive using the Notion SDK and Google Drive API, and provides a cleanup script to move migrated pages to trash.

## Scripts Included

1. **`notion_to_gdrive_migrator.py`** - Main migration script that copies attachments from Notion to Google Drive
2. **`trash_migrated_pages.py`** - Cleanup script that moves successfully migrated Notion pages to trash

## Features

- Automatically identifies Notion pages with single attachments
- Downloads attachments from Notion
- Uploads files to Google Drive with proper metadata
- Creates subfolders based on Notion database names for organized storage
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
4. **Creates Subfolders**: For pages from databases, creates subfolders in Google Drive named after the database
5. **Downloads Files**: Downloads attachments from Notion
6. **Uploads to Drive**: Uploads files to Google Drive with descriptive metadata in the appropriate subfolder
7. **Logs Progress**: Provides detailed logging of the migration process

### Subfolder Organization

The script automatically organizes files by creating subfolders based on the Notion database names:

- **Database Pages**: Files from pages that belong to a Notion database are uploaded to a subfolder named after that database
- **Standalone Pages**: Files from standalone pages (not in a database) are uploaded to the main target folder or root
- **Folder Naming**: Database names are sanitized for Google Drive compatibility (special characters removed, spaces preserved)
- **Folder Reuse**: If a subfolder already exists, it will be reused rather than creating duplicates
- **Caching**: Database folder mappings are cached during execution for improved performance

**Example folder structure:**
```
Google Drive Target Folder/
├── My Project Database/
│   ├── attachment1.pdf
│   └── image2.png
├── Research Notes/
│   ├── document3.pdf
│   └── screenshot4.png
└── standalone_file.jpg (from non-database page)
```

### Output

The script will:
- Display progress in the console
- Create a timestamped `migration_YYYYMMDD_HHMMSS.log` file with detailed logs
- Show a summary of migration results at the end
- Preserve original Notion page creation and modification timestamps on uploaded files

## Cleaning Up Migrated Pages

After successfully migrating your files, you can use the cleanup script to move the original Notion pages to trash:

```bash
# First, do a dry run to see what would be trashed
python trash_migrated_pages.py migration_20250123_143022.log --dry-run

# Then actually move the pages to trash
python trash_migrated_pages.py migration_20250123_143022.log
```

### Trash Script Features

- **Safe Operation**: Includes a `--dry-run` option to preview what will be trashed
- **Log Parsing**: Automatically extracts successfully migrated pages from migration log files
- **Detailed Logging**: Creates its own timestamped log file for the trash operation
- **Error Handling**: Continues processing even if some pages fail to trash
- **URL Extraction**: Parses Notion URLs from migration logs and converts them to page IDs

### Trash Script Usage

```bash
python trash_migrated_pages.py <log_file> [--dry-run]
```

**Arguments:**
- `log_file`: Path to the migration log file (e.g., `migration_20250123_143022.log`)
- `--dry-run`: (Optional) Show what would be trashed without actually doing it

**Example:**
```bash
# Preview what will be trashed
python trash_migrated_pages.py migration_20250123_143022.log --dry-run

# Actually move pages to trash
python trash_migrated_pages.py migration_20250123_143022.log
```

The trash script will:
1. Parse the migration log file to find successfully migrated pages
2. Extract Notion URLs and convert them to page IDs
3. Use the Notion API to move each page to trash (archive it)
4. Generate a detailed log of the trash operation
5. Provide a summary of results

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
