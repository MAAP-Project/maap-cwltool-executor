#!/usr/bin/env python3
"""
Background Docker container metrics monitor for cwltool

Watches cidfile directory and collects time-series metrics from Docker containers
spawned by cwltool during CWL workflow execution.
"""

import os
import sys
import time
import json
import signal
import subprocess
import re
from datetime import datetime
from pathlib import Path
from threading import Thread, Event


class DockerStatsMonitor:
    """Monitor Docker containers and collect time-series metrics"""

    def __init__(self, cidfile_dir, interval_seconds=30):
        """
        Initialize Docker stats monitor

        Args:
            cidfile_dir: Directory containing .cid files from cwltool
            interval_seconds: Sampling interval in seconds (default: 30)
        """
        self.cidfile_dir = Path(cidfile_dir)
        self.interval = int(interval_seconds)
        self.stop_event = Event()
        self.containers = {}  # {container_id: container_data}
        self.output_file = self.cidfile_dir / "_docker_stats.json"
        self.start_time = datetime.utcnow()

        # Threads
        self.watcher_thread = None
        self.collector_thread = None

    def start(self):
        """Start monitoring threads"""
        print(f"[Docker Monitor] Starting (interval: {self.interval}s)", flush=True)

        # Start cidfile watcher thread
        self.watcher_thread = Thread(target=self.watch_cidfiles, daemon=True)
        self.watcher_thread.start()

        # Start stats collector thread
        self.collector_thread = Thread(target=self.collect_stats, daemon=True)
        self.collector_thread.start()

    def stop(self, signum=None, frame=None):
        """Stop monitoring gracefully"""
        print("[Docker Monitor] Stopping...", flush=True)
        self.stop_event.set()

        # Write final metrics
        try:
            self.write_metrics(final=True)
            print(f"[Docker Monitor] Final metrics written to {self.output_file}", flush=True)
        except Exception as e:
            print(f"[Docker Monitor] Error writing final metrics: {e}", flush=True)

        sys.exit(0)

    def watch_cidfiles(self):
        """Continuously watch for new .cid files"""
        while not self.stop_event.is_set():
            try:
                for cidfile in self.cidfile_dir.glob("*.cid"):
                    self.register_container(cidfile)
            except Exception as e:
                print(f"[Docker Monitor] Error watching cidfiles: {e}", flush=True)

            time.sleep(5)  # Check for new containers every 5s

    def register_container(self, cidfile):
        """
        Register a container for monitoring

        Args:
            cidfile: Path to .cid file containing container ID
        """
        try:
            container_id = cidfile.read_text().strip()

            if container_id and container_id not in self.containers:
                # Get container info
                info = self.get_container_info(container_id)
                if info:
                    self.containers[container_id] = {
                        "container_id": container_id,
                        "container_name": info.get("name", "unknown"),
                        "cidfile": cidfile.name,
                        "image": info.get("image", "unknown"),
                        "metrics": [],
                        "start_time": datetime.utcnow().isoformat() + "Z"
                    }
                    print(f"[Docker Monitor] Registered container {container_id[:12]} ({info.get('name')})", flush=True)
        except Exception as e:
            print(f"[Docker Monitor] Error registering container from {cidfile.name}: {e}", flush=True)

    def get_container_info(self, container_id):
        """
        Get container metadata using docker inspect

        Args:
            container_id: Docker container ID

        Returns:
            Dict with container name and image, or None if not found
        """
        try:
            cmd = ["docker", "inspect", "--format", "{{json .}}", container_id]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)

            if result.returncode == 0:
                info = json.loads(result.stdout)
                return {
                    "name": info.get("Name", "").lstrip("/"),
                    "image": info.get("Config", {}).get("Image", "unknown")
                }
        except Exception as e:
            print(f"[Docker Monitor] Error getting container info for {container_id[:12]}: {e}", flush=True)

        return None

    def collect_stats(self):
        """Collect stats for all registered containers at configured interval"""
        while not self.stop_event.is_set():
            if self.containers:
                timestamp = datetime.utcnow().isoformat() + "Z"

                for container_id in list(self.containers.keys()):
                    stats = self.get_container_stats(container_id)
                    if stats:
                        self.containers[container_id]["metrics"].append({
                            "timestamp": timestamp,
                            **stats
                        })

                # Write snapshot to file
                try:
                    self.write_metrics()
                except Exception as e:
                    print(f"[Docker Monitor] Error writing metrics: {e}", flush=True)

            # Wait for next interval
            self.stop_event.wait(self.interval)

    def get_container_stats(self, container_id):
        """
        Get current stats for a container using docker stats

        Args:
            container_id: Docker container ID

        Returns:
            Dict with parsed metrics, or None if container not found/accessible
        """
        try:
            cmd = [
                "docker", "stats", "--no-stream", "--no-trunc",
                "--format", "{{json .}}", container_id
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)

            if result.returncode == 0 and result.stdout.strip():
                stats_json = json.loads(result.stdout)
                return self.parse_stats(stats_json)
        except subprocess.TimeoutExpired:
            print(f"[Docker Monitor] Timeout getting stats for {container_id[:12]}", flush=True)
        except Exception as e:
            # Container may have exited, which is normal
            pass

        return None

    def parse_stats(self, stats_json):
        """
        Parse docker stats JSON to standardized format

        Args:
            stats_json: Raw docker stats JSON output

        Returns:
            Dict with normalized metrics
        """
        # Parse CPU percentage (e.g., "45.32%")
        cpu_str = stats_json.get("CPUPerc", "0%").replace("%", "")
        try:
            cpu_percent = float(cpu_str) if cpu_str else 0.0
        except ValueError:
            cpu_percent = 0.0

        # Parse memory (e.g., "1.5GiB / 4GiB")
        mem_usage = self.parse_memory(stats_json.get("MemUsage", "0B / 0B"))

        # Parse network (e.g., "1.2MB / 500kB")
        net_io = self.parse_network(stats_json.get("NetIO", "0B / 0B"))

        # Parse block I/O (e.g., "1.2MB / 500kB")
        block_io = self.parse_block_io(stats_json.get("BlockIO", "0B / 0B"))

        # Parse memory percentage
        mem_perc_str = stats_json.get("MemPerc", "0%").replace("%", "")
        try:
            mem_percent = float(mem_perc_str) if mem_perc_str else 0.0
        except ValueError:
            mem_percent = 0.0

        return {
            "cpu_percent": cpu_percent,
            "memory_usage_mb": mem_usage["usage_mb"],
            "memory_limit_mb": mem_usage["limit_mb"],
            "memory_percent": mem_percent,
            "network_rx_mb": net_io["rx_mb"],
            "network_tx_mb": net_io["tx_mb"],
            "block_read_mb": block_io["read_mb"],
            "block_write_mb": block_io["write_mb"]
        }

    def parse_memory(self, mem_str):
        """
        Parse memory string (e.g., "1.5GiB / 4GiB")

        Returns:
            Dict with usage_mb, limit_mb, percent
        """
        try:
            parts = mem_str.split("/")
            usage_mb = self.parse_size_to_mb(parts[0].strip())
            limit_mb = self.parse_size_to_mb(parts[1].strip()) if len(parts) > 1 else 0.0

            percent = (usage_mb / limit_mb * 100) if limit_mb > 0 else 0.0

            return {
                "usage_mb": usage_mb,
                "limit_mb": limit_mb,
                "percent": percent
            }
        except Exception:
            return {"usage_mb": 0.0, "limit_mb": 0.0, "percent": 0.0}

    def parse_network(self, net_str):
        """
        Parse network I/O string (e.g., "1.2MB / 500kB")

        Returns:
            Dict with rx_mb (received) and tx_mb (transmitted)
        """
        try:
            parts = net_str.split("/")
            rx_mb = self.parse_size_to_mb(parts[0].strip())
            tx_mb = self.parse_size_to_mb(parts[1].strip()) if len(parts) > 1 else 0.0

            return {"rx_mb": rx_mb, "tx_mb": tx_mb}
        except Exception:
            return {"rx_mb": 0.0, "tx_mb": 0.0}

    def parse_block_io(self, block_str):
        """
        Parse block I/O string (e.g., "100MB / 50MB")

        Returns:
            Dict with read_mb and write_mb
        """
        try:
            parts = block_str.split("/")
            read_mb = self.parse_size_to_mb(parts[0].strip())
            write_mb = self.parse_size_to_mb(parts[1].strip()) if len(parts) > 1 else 0.0

            return {"read_mb": read_mb, "write_mb": write_mb}
        except Exception:
            return {"read_mb": 0.0, "write_mb": 0.0}

    def parse_size_to_mb(self, size_str):
        """
        Parse size string to megabytes (e.g., "1.5GiB" -> 1536.0)

        Args:
            size_str: Size string with unit (B, kB, MB, GB, KiB, MiB, GiB)

        Returns:
            Size in megabytes (float)
        """
        size_str = size_str.strip()

        # Match number and unit
        match = re.match(r'([0-9.]+)\s*([A-Za-z]*)', size_str)
        if not match:
            return 0.0

        value = float(match.group(1))
        unit = match.group(2).upper()

        # Convert to MB
        conversions = {
            "B": 1 / (1024 * 1024),
            "KB": 1 / 1024,
            "MB": 1,
            "GB": 1024,
            "TB": 1024 * 1024,
            "KIB": 1 / 1024,
            "MIB": 1,
            "GIB": 1024,
            "TIB": 1024 * 1024,
        }

        return value * conversions.get(unit, 1)

    def calculate_summary(self):
        """
        Calculate summary statistics across all containers

        Returns:
            Dict with aggregate statistics
        """
        if not self.containers:
            return {
                "total_containers": 0,
                "total_duration_seconds": 0,
                "cpu_percent_max_across_all": 0,
                "memory_mb_max_across_all": 0,
                "network_total_rx_mb": 0,
                "network_total_tx_mb": 0
            }

        cpu_max = 0.0
        mem_max = 0.0
        net_rx_total = 0.0
        net_tx_total = 0.0

        for container in self.containers.values():
            # Calculate per-container summary
            if container["metrics"]:
                container_cpu_max = max((m["cpu_percent"] for m in container["metrics"]), default=0)
                container_mem_max = max((m["memory_usage_mb"] for m in container["metrics"]), default=0)

                # Last sample has cumulative network stats
                last_metric = container["metrics"][-1]
                container_net_rx = last_metric.get("network_rx_mb", 0)
                container_net_tx = last_metric.get("network_tx_mb", 0)

                # Add per-container summary
                container["summary"] = {
                    "duration_seconds": len(container["metrics"]) * self.interval,
                    "samples_collected": len(container["metrics"]),
                    "cpu_percent_avg": sum(m["cpu_percent"] for m in container["metrics"]) / len(container["metrics"]),
                    "cpu_percent_max": container_cpu_max,
                    "memory_mb_avg": sum(m["memory_usage_mb"] for m in container["metrics"]) / len(container["metrics"]),
                    "memory_mb_max": container_mem_max,
                    "network_rx_mb_total": container_net_rx,
                    "network_tx_mb_total": container_net_tx
                }

                # Update global maxes
                cpu_max = max(cpu_max, container_cpu_max)
                mem_max = max(mem_max, container_mem_max)
                net_rx_total += container_net_rx
                net_tx_total += container_net_tx

        end_time = datetime.utcnow()
        duration = (end_time - self.start_time).total_seconds()

        return {
            "total_containers": len(self.containers),
            "total_duration_seconds": int(duration),
            "cpu_percent_max_across_all": round(cpu_max, 2),
            "memory_mb_max_across_all": round(mem_max, 2),
            "network_total_rx_mb": round(net_rx_total, 2),
            "network_total_tx_mb": round(net_tx_total, 2)
        }

    def write_metrics(self, final=False):
        """
        Write current metrics snapshot to file

        Args:
            final: If True, calculate per-container summaries
        """
        end_time = datetime.utcnow().isoformat() + "Z"

        output = {
            "config": {
                "sampling_interval_seconds": self.interval,
                "start_time": self.start_time.isoformat() + "Z",
                "end_time": end_time
            },
            "containers": list(self.containers.values()),
            "summary_all_containers": self.calculate_summary() if final else {}
        }

        # Atomic write
        temp_file = self.output_file.with_suffix(".tmp")
        with open(temp_file, 'w') as f:
            json.dump(output, f, indent=2)
        temp_file.replace(self.output_file)


def main():
    """Main entry point"""
    if len(sys.argv) < 2:
        print("Usage: monitor_docker_stats.py <cidfile_dir> [interval_seconds]", file=sys.stderr)
        sys.exit(1)

    cidfile_dir = sys.argv[1]
    interval = int(sys.argv[2]) if len(sys.argv) > 2 else int(os.getenv('DOCKER_STATS_INTERVAL', '30'))

    # Validate interval
    if interval < 5 or interval > 300:
        print(f"Warning: Interval {interval}s outside recommended range (5-300s). Using 30s.", file=sys.stderr)
        interval = 30

    # Create monitor
    monitor = DockerStatsMonitor(cidfile_dir, interval)

    # Setup signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, monitor.stop)
    signal.signal(signal.SIGINT, monitor.stop)

    # Start monitoring
    monitor.start()

    # Keep main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        monitor.stop()


if __name__ == "__main__":
    main()
