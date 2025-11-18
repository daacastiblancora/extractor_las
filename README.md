# Well Log Metadata Extractor

A Python-based pipeline for extracting metadata from petroleum industry well logging files in LAS, LIS, and DLIS formats.

## Features

- **Multi-format Support**: Processes LAS, LIS, and DLIS well log files
- **Intelligent Format Detection**: Automatically detects file format based on content, not just extension
- **Robust Error Handling**: Fallback mechanisms for corrupted or non-standard files
- **Multiple Output Formats**:
  - Raw JSON metadata
  - OSDU-compliant JSON
  - Human-readable Markdown reports
- **Resumable Processing**: Can resume interrupted batch processing
- **Comprehensive Logging**: Detailed logs for debugging and quality control

## Installation

### Requirements

- Python 3.7+
- Required packages:
  ```bash
  pip install lasio dlisio pandas
  ```

### Dependencies

- `lasio` - LAS file parsing (required)
- `dlisio` - DLIS/LIS file parsing (recommended)
- `pandas` - Data manipulation (optional, for enhanced reporting)

## Usage

### Basic Usage

1. Update the configuration paths in `extractor_las_corregido_v3.py`:
   ```python
   INPUT_DIR = "/path/to/your/well/logs"
   OUT_DIR = "/path/to/output/directory"
   ```

2. Run the script:
   ```bash
   python extractor_las_corregido_v3.py
   ```

### Configuration

Edit the following variables in the script (lines 71-76):

- `INPUT_DIR`: Directory containing well log files or text file with directory list
- `OUT_DIR`: Output directory for processed metadata
- `STATE_FILE`: State file for resuming interrupted runs
- `UNPROCESSED_STATE_FILE`: Log of files that failed processing
- `BASE_EXTENSIONS`: File extensions to process

## Output Files

For each processed well log file, the script generates:

1. **`{filename}.json`** - Complete metadata extraction in JSON format
2. **`{filename}_osdu.json`** - OSDU-compliant well log metadata
3. **`{filename}_metadata.md`** - Human-readable summary report

## Architecture

### File Format Detection

The script uses a sophisticated multi-stage detection system:

1. Binary corruption check (detects misnamed Office/PDF/ZIP files)
2. Extension-based prioritization
3. Binary signature detection (DLIS SUL, LIS PRH)
4. Text-based fallback for LAS files

### Processing Pipeline

1. **Detection**: Identify file format
2. **Extraction**: Use format-specific parser (lasio/dlisio) with fallback
3. **Transformation**: Generate multiple output formats
4. **State Management**: Track progress for resumability

## Supported File Formats

### LAS (Log ASCII Standard)
- Full support via `lasio` library
- Automatic correction of missing `~A` sections
- Handles non-standard VERS mnemonics
- Text-based fallback parser for corrupted files

### DLIS (Digital Log Interchange Standard)
- Support via `dlisio` library
- Extracts Origin, Parameters, and Channel metadata
- Handles multiple logical files

### LIS (Log Information Standard)
- Support via `dlisio` library
- ASCII string extraction fallback
- Extracts mnemonics, units, and service company info

## Error Handling

- Non-fatal errors trigger fallback extraction methods
- Failed files are logged to unprocessed file list
- Processing continues with next file
- Graceful shutdown on interruption (Ctrl+C)

## Logging

- **File log** (`pipeline_las_informacion_QC_1.log`): Warnings and errors only
- **Console**: Info, warnings, and errors
- **Auto-rotation**: Backs up logs > 50MB

## Development

See [CLAUDE.md](CLAUDE.md) for detailed architecture documentation and development guidelines.

## Author

Daniel Castiblanco R (daacastiblancora@unal.edu.co)

## License

MIT License - Feel free to use and modify for your needs.
