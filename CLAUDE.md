# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Python-based well log metadata extraction pipeline designed to process petroleum industry well logging files in LAS, LIS, and DLIS formats. The script extracts metadata, well information, curve definitions, and generates outputs in multiple formats (JSON, OSDU-compliant JSON, and Markdown).

## Running the Script

### Main Execution
```bash
python extractor_las_corregido_v3.py
```

### Dependencies
Required Python packages:
- `lasio` - For LAS file parsing (CRITICAL)
- `dlisio` - For DLIS/LIS file parsing
- `pandas` - For data manipulation and reporting

Install dependencies:
```bash
pip install lasio dlisio pandas
```

## Key Configuration

The script uses hardcoded Windows paths that need to be updated for your environment:

- **INPUT_DIR** (line 71): Directory containing well log files or a text file listing directories to process
- **OUT_DIR** (line 72): Output directory for processed metadata
- **STATE_FILE** (line 73): Stores the last processed file path for resuming interrupted runs
- **UNPROCESSED_STATE_FILE** (line 74): Log of files that failed processing

**Important**: Update these paths before running on Linux or different directories.

## Architecture

### File Format Detection (`detect_file_format()`)

The script implements a sophisticated multi-stage detection system:

1. **Binary corruption check** - Detects Microsoft Office files, ZIPs, PDFs with wrong extensions
2. **Extension-based prioritization** - `.las`/`.dlas` files are treated as text first, `.lis` files are treated as binary first
3. **Binary signature detection** - Identifies DLIS SUL headers and LIS Physical Record Headers
4. **Text-based fallback** - Searches for LAS section markers (`~V`, `~W`, etc.)

### Format-Specific Extractors

#### LAS Files (`extract_metadata_from_las()`)
- Primary: Uses `lasio.read()` with preprocessing to fix missing `~A` sections and rename conflicting `VERS` mnemonics
- Fallback: Regex-based text parsing if lasio fails
- Handles non-standard LAS files with header corrections

#### DLIS Files (`extract_metadata_from_dlis()`)
- Uses `dlisio.dlis.load()` to read logical files
- Extracts Origin metadata, Parameters, and Channel/Frame information
- Falls back to basic binary info extraction if dlisio fails

#### LIS Files (`extract_metadata_from_lis()`)
- Uses `dlisio.lis.load()` for structured parsing
- Falls back to `extract_lis_strings()` which scans for ASCII strings containing:
  - Service company names (Schlumberger, Halliburton, etc.)
  - Date patterns (`YY/MM/DD`)
  - Mnemonic definitions (`MNEM`, `PUNI`, `TUNI`, `VALU`)
  - Tool types and parameters

### Processing Pipeline (`process_file()`)

1. **Metadata Extraction** - Calls format-specific extractor
2. **Raw JSON Output** - Saves complete metadata as `{filename}.json`
3. **OSDU JSON Generation** - Creates OSDU-compliant well log JSON as `{filename}_osdu.json`
4. **Markdown Report** - Generates human-readable summary as `{filename}_metadata.md`

### Resumption Logic

The script maintains state to resume interrupted processing:
- Reads `STATE_FILE` to find the last successfully processed file
- Skips already-processed files when restarting
- Logs unprocessed files to `UNPROCESSED_STATE_FILE`

## Key Data Structures

### Field Aliases (FIELD_ALIASES, line 79-95)
Maps canonical names to common mnemonic variations found in well logs. For example:
- `COMPANY` → `["COMP", "COMPANY", "CMPY"]`
- `WELL` → `["WELL", "WELL NAME", "WELLNAME"]`

### Metadata Dictionary Structure
```python
{
    "format": "LAS|DLIS|LIS",
    "header": {
        "Well": {...},      # Well information mnemonics
        "Parameter": {...}, # Parameter section
        "Origin": {...}     # DLIS/LIS origin info
    },
    "curves": [            # List of logging curves
        {"mnemonic": "GR", "unit": "GAPI", "descr": "Gamma Ray"}
    ],
    "actual_start_md": float,  # Measured depth start
    "actual_end_md": float,    # Measured depth end
    "actual_md_unit": str,     # Depth unit
    "raw_las_content": dict|str,
    "note": str                # Processing notes
}
```

## Important Implementation Details

### LAS Preprocessing
- **Missing `~A` section** (line 341): Automatically inserts `~A` header if missing before data section
- **VERS conflicts** (line 379, 405): Renames `VERS` mnemonics in `~P` and `~C` sections to avoid lasio KeyError

### Character Encoding
- Tries multiple encodings: `utf-8`, `latin-1`, `cp1252`, `ascii`
- Configures stdout/stderr for UTF-8 with error replacement
- Uses `errors='replace'` when writing JSON/text to prevent encoding crashes

### Logging Strategy
- **File log**: Only WARNING and ERROR messages (prevents large log files)
- **Console**: INFO, WARNING, and ERROR messages
- **Log rotation**: Automatically backs up logs > 50MB

### Error Handling
- Non-fatal errors: Logs warning and attempts fallback extraction
- Fatal errors: Logs to unprocessed file list and continues with next file
- Signal handling: Graceful shutdown on SIGINT/SIGTERM

## Common Modifications

### Adding New File Extensions
Update `BASE_EXTENSIONS` (line 75):
```python
BASE_EXTENSIONS = [".las", ".lis", ".dlis", ".dlas", ".new_extension"]
```

### Adding New Field Aliases
Add to `FIELD_ALIASES` dictionary (line 79):
```python
"NEW_FIELD": ["ALIAS1", "ALIAS2", "ALIAS3"]
```

### Customizing OSDU Output
Modify the `osdu_data` dictionary construction in `process_file()` (line 1116)

### Changing Output Formats
- Raw JSON: Line 1080
- OSDU JSON: Line 1135
- Markdown: Line 1180

## Notes

- The script processes files sequentially (no parallel processing)
- Memory usage is kept low by processing one file at a time
- The script is designed for batch processing large directories of well logs
- Progress can be monitored through console output and log files
