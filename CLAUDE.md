# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This repository contains a MAAP CWLTOOL EXECUTOR that executes OGC EO APP package jobs on the MAAP HySDS platform using cwltool. The system processes geospatial data through CWL (Common Workflow Language) workflows, particularly for Sentinel-1 data processing.

## Core Architecture

The system follows a job execution pipeline:

1. **Job Context Processing** (`_context.json`) - Contains HySDS job parameters and specifications
2. **Input Generation** (`create_inputs.py`) - Converts job context to CWL-compatible inputs
3. **Asset Staging** (`stage_in.py`) - Downloads STAC assets using MAAP API
4. **CWL Execution** (`dps_wrapper.sh`) - Runs cwltool with generated inputs
5. **Output Stage-Out** (`stage_out.py`) - Discovers and processes CWL-defined outputs
6. **Dataset Creation** (`process_outputs.py`) - Processes CWL outputs and creates HySDS-compatible datasets

### Key Components

- **create_inputs.py**: Parses CWL files to understand required inputs, maps HySDS job parameters to CWL format, handles STAC item localization for Directory inputs
- **stage_in.py**: Downloads STAC item assets using maap-py library, creates local STAC catalogs with relative paths
- **dps_wrapper.sh**: Main execution script that sets up MAAP environment, downloads CWL files from S3, executes cwltool with proper parameters
- **stage_out.py**: Discovers actual output paths from CWL output definitions using glob patterns, validates and extracts metadata from STAC catalogs
- **hysds_metadata.py**: Centralizes HySDS metadata creation logic, handles both STAC and non-STAC outputs
- **process_outputs.py**: Processes multiple CWL outputs, creates timestamped HySDS datasets, and generates metadata files directly using hysds_metadata module

## Dependencies

Core dependencies are defined in `environment.yaml`:
- cwltool==3.1.20250110105449 (specific version for reproducibility)
- cwl_utils==0.35 (for CWL parsing)
- pystac (STAC catalog handling)
- maap-py (MAAP API integration)
- pyyaml, nodejs

## Development Commands

The system is primarily designed to run within Docker containers on the HySDS platform. For local development:

```bash
# Build Docker image
docker build -t maap-cwltool-executor -f docker/Dockerfile .

# Test input creation (requires _context.json)
python create_inputs.py <cwl_file_path>

# Test STAC asset staging
python stage_in.py --stac-item-filepath <stac_item.json> --output-dir <output_dir>

# Test output stage-out (discovers CWL-defined outputs)
python stage_out.py <cwl_file_path>
```

## Environment Setup

The system requires MAAP environment variables:
- `MAAP_API_HOST` - MAAP API endpoint
- `DPS_MACHINE_TOKEN` - Authentication token
- `MAAP_PGT` - Proxy granting ticket (obtained dynamically)

## CWL Input Types

The system handles three CWL input types:
- **Directory**: Treated as STAC items, assets are downloaded and localized
- **File**: Files are referenced by basename, expected to be pre-staged
- **Primitive types**: Passed through as string values

## Output Structure

The system now uses CWL-defined outputs with intelligent discovery:

### Stage-Out Process
1. **CWL Output Parsing**: Extracts output definitions from CWL file
2. **Pattern Resolution**: Uses `outputBinding.glob` patterns to find actual files/directories
3. **STAC Validation**: Identifies and validates Directory outputs as STAC catalogs
4. **Fallback Behavior**: Uses default `output` directory when CWL outputs not defined

### Output Types Handled
- **File outputs**: Individual files specified by glob patterns
- **Directory outputs**: 
  - Regular directories copied as-is
  - STAC catalogs validated using pystac library
- **Primitive outputs**: Stored in metadata

### HySDS Dataset Structure

#### Multiple CWL Outputs
The system now supports multiple CWL outputs, creating a separate HySDS dataset for each:

```
CWL with outputs:
  collection1/ (Directory with catalog.json)
  collection2/ (Directory with catalog.json)

Creates datasets:
  collection1-2025-12-16T11:30:00.123456/
  collection2-2025-12-16T11:30:00.123456/
```

#### Single Dataset Structure
Final outputs follow HySDS dataset conventions:
- `<dataset_name>/` directory containing discovered outputs
- `<dataset_name>.dataset.json` with HySDS configuration
- `<dataset_name>.met.json` with job execution and STAC catalog metadata
- Standard output/error logs copied to dataset directory
- STAC catalog files preserved unchanged (if present)

#### STAC Catalog Integration

When a CWL output Directory contains a STAC catalog (catalog.json), the system:
1. **Preserves STAC structure**: Catalog, collections, and items remain unchanged
2. **Enhances HySDS metadata**: `.met.json` contains complete STAC inventory
3. **Maintains STAC compliance**: pystac.read_file() still works on output catalogs
4. **Enables discovery**: Full item inventory in `.met.json` for search/indexing

#### Metadata File Schemas

**`.dataset.json`** (HySDS configuration):
```json
{
  "version": "v1.0",
  "stac_enabled": true,        // if STAC output
  "stac_catalog_id": "...",    // if STAC output
  "stac_collections": [...],   // if STAC output
  "total_items": 7,             // if STAC output
  "output_type": "stac_catalog" // if STAC output
}
```

**`.met.json`** (Job metadata + optional STAC inventory):
```json
{
  "username": "...",
  "algorithm_name": "...",
  "algorithm_version": "...",
  "tag": "...",
  "stac_catalog": {             // if STAC output
    "id": "...",
    "description": "...",
    "stac_version": "1.1.0",
    "collections": [
      {
        "id": "...",
        "item_count": 7,
        "items": [
          {
            "id": "item_001",
            "collection": "...",
            "datetime": "...",
            "bbox": [...],
            "assets": {...},
            "properties": {...}
          },
          // ... all items included
        ]
      }
    ]
  }
}
```

### Stage-Out and Dataset Creation Flow

1. **stage_out.py** (`--json-output`):
   - Discovers all CWL outputs
   - For each Directory output, extracts STAC metadata (if present)
   - Returns JSON with output list and metadata

2. **process_outputs.py**:
   - Processes each output independently
   - Creates timestamped dataset directory for each output
   - Saves STAC metadata as reference file in dataset
   - Reads job metadata from `_job.json`
   - Creates `.dataset.json` and `.met.json` using hysds_metadata module directly

3. **Result**:
   - Multiple HySDS datasets (one per CWL output)
   - Each dataset with appropriate HySDS metadata
   - STAC catalogs preserved with complete item inventory in met.json