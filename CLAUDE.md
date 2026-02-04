# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This repository contains a MAAP CWLTOOL EXECUTOR that executes OGC EO APP package jobs on the MAAP HySDS platform using cwltool. The system processes geospatial data through CWL (Common Workflow Language) workflows, particularly for Sentinel-1 data processing.

## Core Architecture

The system follows a job execution pipeline:

1. **Job Context Processing** (`_context.json`) - Contains HySDS job parameters and specifications
2. **Input Generation** (`create_inputs.py`) - Converts job context to CWL-compatible inputs
3. **Asset Staging** (`stage_in.py`) - Downloads STAC assets using MAAP API
4. **Metrics Monitoring** (`monitor_docker_stats.py`) - Background process starts to collect container metrics
5. **CWL Execution** (`dps_wrapper.sh`) - Runs cwltool with generated inputs while metrics are collected
6. **Metrics Finalization** - Monitor stopped, final metrics written to `_docker_stats.json`
7. **Output Stage-Out** (`stage_out.py`) - Discovers and processes CWL-defined outputs
8. **Dataset Creation** (`process_outputs.py`) - Processes CWL outputs, creates HySDS datasets, copies logs and metrics

### Key Components

- **create_inputs.py**: Parses CWL files to understand required inputs, maps HySDS job parameters to CWL format, handles STAC item localization for Directory inputs
- **stage_in.py**: Downloads STAC item assets using maap-py library, creates local STAC catalogs with relative paths
- **dps_wrapper.sh**: Main execution script that sets up MAAP environment, downloads CWL files from S3, executes cwltool with proper parameters, manages Docker metrics collection
- **monitor_docker_stats.py**: Background process that watches for Docker containers spawned by cwltool and collects continuous resource usage metrics (CPU, memory, network, I/O)
- **stage_out.py**: Discovers actual output paths from CWL output definitions using glob patterns, validates and extracts metadata from STAC catalogs
- **hysds_metadata.py**: Centralizes HySDS metadata creation logic, handles both STAC and non-STAC outputs
- **process_outputs.py**: Processes multiple CWL outputs, creates timestamped HySDS datasets, generates metadata files, and copies logs and metrics to output datasets

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

### Docker Metrics Collection

The system automatically collects continuous resource usage metrics from Docker containers spawned by cwltool during workflow execution.

#### Configuration
- **Environment Variable**: `DOCKER_STATS_INTERVAL` (default: 30 seconds)
- **Valid Range**: 5-300 seconds
- **Set via**: HySDS job spec, Dockerfile ENV, or Docker run command

#### How It Works
1. **Background Monitoring** (`monitor_docker_stats.py`):
   - Starts before cwltool execution
   - Watches `--cidfile-dir` for new container ID files
   - Collects metrics at configured interval using `docker stats`
   - Writes time-series data to `_docker_stats.json`
   - Stops gracefully after cwltool completes

2. **Integration** (`dps_wrapper.sh`):
   - Launches monitor in background before cwltool
   - Captures monitor PID for graceful shutdown
   - Sends SIGTERM signal on completion
   - Ensures final metrics are written

3. **Output** (`process_outputs.py`):
   - Copies `_docker_stats.json` to each output dataset
   - File preserved alongside `_stdout.txt` and `_stderr.txt`

#### Metrics Collected
For each Docker container:
- **CPU**: Usage percentage over time
- **Memory**: Usage (MB), limit (MB), percentage
- **Network**: Received/transmitted data (MB)
- **Block I/O**: Read/write operations (MB)
- **Timestamps**: UTC timestamps for each sample

#### Output Format
`_docker_stats.json` contains:
```json
{
  "config": {
    "sampling_interval_seconds": 30,
    "start_time": "2026-02-04T12:00:00Z",
    "end_time": "2026-02-04T12:10:00Z"
  },
  "containers": [
    {
      "container_id": "9a24e0e88f1d...",
      "container_name": "...",
      "cidfile": "20260204120000-123456.cid",
      "image": "ghcr.io/...",
      "metrics": [
        {
          "timestamp": "2026-02-04T12:00:00Z",
          "cpu_percent": 15.3,
          "memory_usage_mb": 1024.5,
          "memory_limit_mb": 4096.0,
          "memory_percent": 25.0,
          "network_rx_mb": 12.3,
          "network_tx_mb": 5.6,
          "block_read_mb": 100.2,
          "block_write_mb": 50.1
        }
      ],
      "summary": {
        "duration_seconds": 600,
        "samples_collected": 20,
        "cpu_percent_avg": 32.5,
        "cpu_percent_max": 85.2,
        "memory_mb_avg": 1450.3,
        "memory_mb_max": 2048.7
      }
    }
  ],
  "summary_all_containers": {
    "total_containers": 1,
    "cpu_percent_max_across_all": 85.2,
    "memory_mb_max_across_all": 2048.7,
    "network_total_rx_mb": 245.6,
    "network_total_tx_mb": 112.3
  }
}
```

#### Error Handling
- **Non-Critical**: Metrics collection failures do NOT fail the job
- **Graceful Degradation**: Job proceeds without metrics if monitor fails
- **Partial Collection**: Available metrics are written even if some containers exit

#### Integration with HySDS
- HySDS automatically processes `_docker_stats.json` from the job directory
- Metrics are incorporated into HySDS job metadata (`_job.json`)
- Available in HySDS metrics dashboards and reporting tools

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