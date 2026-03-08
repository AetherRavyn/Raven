import base64
import csv
import hashlib
import json
import mimetypes
import os
import re
import shutil
import tarfile
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from app.tools.base import BaseTool, ToolParameter, ToolSchema


class AdvancedFileOperationTool(BaseTool):
    """Advanced comprehensive tool for file and directory operations"""

    def __init__(
        self, base_directory: str = None, max_file_size: int = 10 * 1024 * 1024
    ):
        """
        Initialize file operations tool

        Args:
            base_directory: Optional base directory to restrict operations
            max_file_size: Maximum file size to read in bytes (default 10MB)
        """
        self.base_directory = Path(base_directory).resolve() if base_directory else None
        self.max_file_size = max_file_size
        mimetypes.init()

    def get_name(self) -> str:
        return "file_operations"

    def get_description(self) -> str:
        return """Advanced file and directory operations tool with 35+ operations including:
        file I/O, content manipulation, searching, archiving, hashing, comparison,
        CSV operations, batch processing, and more."""

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="operation",
                    type="string",
                    description="Operation to perform",
                    required=True,
                    enum=[
                        # Basic I/O
                        "read",
                        "write",
                        "append",
                        "read_lines",
                        "read_json",
                        "write_json",
                        # File Management
                        "delete",
                        "copy",
                        "move",
                        "rename",
                        "mkdir",
                        "exists",
                        # Information
                        "info",
                        "list",
                        "tree",
                        "size",
                        "count_lines",
                        "detect_encoding",
                        # Content Manipulation
                        "find_replace",
                        "insert_at_line",
                        "delete_lines",
                        "merge_files",
                        "split_file",
                        "deduplicate_lines",
                        "sort_lines",
                        "reverse_lines",
                        # Search
                        "search",
                        "search_content",
                        "search_regex",
                        "find_duplicates",
                        # Archive Operations
                        "zip_create",
                        "zip_extract",
                        "zip_list",
                        "tar_create",
                        "tar_extract",
                        # Hash/Checksum
                        "hash",
                        "verify_hash",
                        "compare_files",
                        # CSV Operations
                        "csv_read",
                        "csv_write",
                        "csv_append",
                        "csv_filter",
                        # Batch Operations
                        "batch_rename",
                        "batch_delete",
                        "batch_move",
                        # Advanced
                        "create_symlink",
                        "resolve_symlink",
                        "temp_file",
                        "base64_encode",
                        "base64_decode",
                        "mimetype",
                        "permissions_change",
                    ],
                ),
                ToolParameter(
                    name="filepath",
                    type="string",
                    description="Path to the file or directory",
                    required=True,
                ),
                ToolParameter(
                    name="content",
                    type="string",
                    description="Content for write/append/replace operations",
                    required=False,
                ),
                ToolParameter(
                    name="destination",
                    type="string",
                    description="Destination path for copy/move operations",
                    required=False,
                ),
                ToolParameter(
                    name="pattern",
                    type="string",
                    description="Search pattern, regex, or glob pattern",
                    required=False,
                ),
                ToolParameter(
                    name="replacement",
                    type="string",
                    description="Replacement string for find_replace operations",
                    required=False,
                ),
                ToolParameter(
                    name="line_number",
                    type="integer",
                    description="Line number for insert/delete operations (1-indexed)",
                    required=False,
                ),
                ToolParameter(
                    name="start_line",
                    type="integer",
                    description="Start line number for range operations",
                    required=False,
                ),
                ToolParameter(
                    name="end_line",
                    type="integer",
                    description="End line number for range operations",
                    required=False,
                ),
                ToolParameter(
                    name="recursive",
                    type="boolean",
                    description="Perform operation recursively",
                    required=False,
                ),
                ToolParameter(
                    name="encoding",
                    type="string",
                    description="File encoding (default: utf-8)",
                    required=False,
                ),
                ToolParameter(
                    name="create_dirs",
                    type="boolean",
                    description="Create parent directories if needed",
                    required=False,
                ),
                ToolParameter(
                    name="overwrite",
                    type="boolean",
                    description="Overwrite existing files",
                    required=False,
                ),
                ToolParameter(
                    name="max_depth",
                    type="integer",
                    description="Maximum depth for tree/search operations",
                    required=False,
                ),
                ToolParameter(
                    name="case_sensitive",
                    type="boolean",
                    description="Case sensitive search/replace",
                    required=False,
                ),
                ToolParameter(
                    name="hash_algorithm",
                    type="string",
                    description="Hash algorithm (md5, sha1, sha256, sha512)",
                    required=False,
                ),
                ToolParameter(
                    name="expected_hash",
                    type="string",
                    description="Expected hash value for verification",
                    required=False,
                ),
                ToolParameter(
                    name="delimiter",
                    type="string",
                    description="Delimiter for CSV operations (default: comma)",
                    required=False,
                ),
                ToolParameter(
                    name="headers",
                    type="array",
                    description="Column headers for CSV operations",
                    required=False,
                ),
                ToolParameter(
                    name="filter_column",
                    type="string",
                    description="Column name for CSV filtering",
                    required=False,
                ),
                ToolParameter(
                    name="filter_value",
                    type="string",
                    description="Value to filter by in CSV",
                    required=False,
                ),
                ToolParameter(
                    name="compression",
                    type="string",
                    description="Compression type for archives (gz, bz2, xz)",
                    required=False,
                ),
                ToolParameter(
                    name="chunk_size",
                    type="integer",
                    description="Chunk size for split operations (in bytes or lines)",
                    required=False,
                ),
                ToolParameter(
                    name="permissions",
                    type="string",
                    description="Permissions in octal format (e.g., '755', '644')",
                    required=False,
                ),
                ToolParameter(
                    name="files",
                    type="array",
                    description="List of files for batch operations",
                    required=False,
                ),
            ],
        )

    def _validate_path(self, filepath: str) -> Path:
        """Validate and resolve file path"""
        path = Path(filepath).resolve()
        if self.base_directory:
            try:
                path.relative_to(self.base_directory)
            except ValueError:
                raise PermissionError(f"Access denied: Path outside base directory")
        return path

    def _human_readable_size(self, size: int) -> str:
        """Convert bytes to human-readable format"""
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} PB"

    def _get_file_info(self, path: Path) -> Dict[str, Any]:
        """Get detailed file/directory information"""
        stat = path.stat()
        return {
            "name": path.name,
            "path": str(path),
            "type": "directory" if path.is_dir() else "file",
            "size": stat.st_size if path.is_file() else None,
            "size_human": self._human_readable_size(stat.st_size)
            if path.is_file()
            else None,
            "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "accessed": datetime.fromtimestamp(stat.st_atime).isoformat(),
            "permissions": oct(stat.st_mode)[-3:],
            "is_file": path.is_file(),
            "is_directory": path.is_dir(),
            "is_symlink": path.is_symlink(),
            "extension": path.suffix if path.is_file() else None,
            "mimetype": mimetypes.guess_type(str(path))[0] if path.is_file() else None,
        }

    def _calculate_hash(self, path: Path, algorithm: str = "sha256") -> str:
        """Calculate file hash"""
        hash_func = getattr(hashlib, algorithm)()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_func.update(chunk)
        return hash_func.hexdigest()

    def _search_in_file(
        self, path: Path, pattern: str, regex: bool = False, case_sensitive: bool = True
    ) -> List[Dict[str, Any]]:
        """Search for pattern in file content"""
        matches = []
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for line_num, line in enumerate(f, 1):
                    if regex:
                        flags = 0 if case_sensitive else re.IGNORECASE
                        if re.search(pattern, line, flags):
                            matches.append(
                                {
                                    "line_number": line_num,
                                    "line": line.rstrip("\n"),
                                    "file": str(path),
                                }
                            )
                    else:
                        search_line = line if case_sensitive else line.lower()
                        search_pattern = pattern if case_sensitive else pattern.lower()
                        if search_pattern in search_line:
                            matches.append(
                                {
                                    "line_number": line_num,
                                    "line": line.rstrip("\n"),
                                    "file": str(path),
                                }
                            )
        except:
            pass
        return matches

    def _directory_tree(
        self, directory: Path, max_depth: int = 3, prefix: str = ""
    ) -> List[str]:
        """Generate directory tree structure"""
        tree = []

        def build_tree(
            current_dir: Path, current_prefix: str = "", current_depth: int = 0
        ):
            if current_depth > max_depth:
                return
            try:
                items = sorted(
                    current_dir.iterdir(), key=lambda x: (not x.is_dir(), x.name)
                )
                for i, item in enumerate(items):
                    is_last = i == len(items) - 1
                    connector = "└── " if is_last else "├── "
                    tree.append(f"{current_prefix}{connector}{item.name}")
                    if item.is_dir():
                        extension = "    " if is_last else "│   "
                        build_tree(item, current_prefix + extension, current_depth + 1)
            except PermissionError:
                tree.append(f"{current_prefix}[Permission Denied]")

        tree.append(str(directory))
        build_tree(directory)
        return tree

    def _detect_encoding(self, path: Path) -> str:
        """Detect file encoding"""
        try:
            # Try common encodings
            encodings = ["utf-8", "utf-16", "ascii", "latin-1", "cp1252"]
            with open(path, "rb") as f:
                raw_data = f.read(10000)  # Read first 10KB

            for encoding in encodings:
                try:
                    raw_data.decode(encoding)
                    return encoding
                except UnicodeDecodeError:
                    continue
            return "unknown"
        except:
            return "error"

    async def execute(
        self,
        operation: str,
        filepath: str,
        content: str = None,
        destination: str = None,
        pattern: str = None,
        replacement: str = None,
        line_number: int = None,
        start_line: int = None,
        end_line: int = None,
        recursive: bool = False,
        encoding: str = "utf-8",
        create_dirs: bool = False,
        overwrite: bool = True,
        max_depth: int = None,
        case_sensitive: bool = True,
        hash_algorithm: str = "sha256",
        expected_hash: str = None,
        delimiter: str = ",",
        headers: List[str] = None,
        filter_column: str = None,
        filter_value: str = None,
        compression: str = None,
        chunk_size: int = None,
        permissions: str = None,
        files: List[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Execute file operation"""
        try:
            path = self._validate_path(filepath)

            # ==================== BASIC I/O ====================
            if operation == "read":
                if not path.exists():
                    return {"success": False, "error": f"File not found: {filepath}"}
                if not path.is_file():
                    return {"success": False, "error": f"Not a file: {filepath}"}
                if path.stat().st_size > self.max_file_size:
                    return {"success": False, "error": f"File too large"}

                with open(path, "r", encoding=encoding) as f:
                    data = f.read()

                return {
                    "success": True,
                    "operation": operation,
                    "filepath": str(path),
                    "content": data,
                    "size": len(data),
                    "lines": data.count("\n") + 1,
                }

            elif operation == "write":
                if content is None:
                    return {"success": False, "error": "Content required"}
                if path.exists() and not overwrite:
                    return {"success": False, "error": "File exists"}
                if create_dirs:
                    path.parent.mkdir(parents=True, exist_ok=True)

                with open(path, "w", encoding=encoding) as f:
                    f.write(content)

                return {
                    "success": True,
                    "operation": operation,
                    "filepath": str(path),
                    "bytes_written": len(content.encode(encoding)),
                }

            elif operation == "append":
                if content is None:
                    return {"success": False, "error": "Content required"}
                if create_dirs:
                    path.parent.mkdir(parents=True, exist_ok=True)

                with open(path, "a", encoding=encoding) as f:
                    f.write(content)

                return {"success": True, "operation": operation, "filepath": str(path)}

            elif operation == "read_lines":
                if not path.is_file():
                    return {"success": False, "error": "Not a file"}

                with open(path, "r", encoding=encoding) as f:
                    lines = [line.rstrip("\n") for line in f.readlines()]

                return {
                    "success": True,
                    "operation": operation,
                    "filepath": str(path),
                    "lines": lines,
                    "line_count": len(lines),
                }

            elif operation == "read_json":
                if not path.is_file():
                    return {"success": False, "error": "Not a file"}

                with open(path, "r", encoding=encoding) as f:
                    data = json.load(f)

                return {
                    "success": True,
                    "operation": operation,
                    "filepath": str(path),
                    "data": data,
                }

            elif operation == "write_json":
                if content is None:
                    return {"success": False, "error": "Content required"}
                if create_dirs:
                    path.parent.mkdir(parents=True, exist_ok=True)

                data = json.loads(content) if isinstance(content, str) else content
                with open(path, "w", encoding=encoding) as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)

                return {"success": True, "operation": operation, "filepath": str(path)}

            # ==================== CONTENT MANIPULATION ====================
            elif operation == "find_replace":
                if not path.is_file():
                    return {"success": False, "error": "Not a file"}
                if pattern is None or replacement is None:
                    return {
                        "success": False,
                        "error": "Pattern and replacement required",
                    }

                with open(path, "r", encoding=encoding) as f:
                    content_data = f.read()

                flags = 0 if case_sensitive else re.IGNORECASE
                new_content = re.sub(pattern, replacement, content_data, flags=flags)
                count = len(re.findall(pattern, content_data, flags=flags))

                with open(path, "w", encoding=encoding) as f:
                    f.write(new_content)

                return {
                    "success": True,
                    "operation": operation,
                    "filepath": str(path),
                    "replacements": count,
                }

            elif operation == "insert_at_line":
                if not path.is_file():
                    return {"success": False, "error": "Not a file"}
                if content is None or line_number is None:
                    return {
                        "success": False,
                        "error": "Content and line_number required",
                    }

                with open(path, "r", encoding=encoding) as f:
                    lines = f.readlines()

                # Insert at specific line (1-indexed)
                insert_pos = max(0, min(line_number - 1, len(lines)))
                lines.insert(
                    insert_pos, content if content.endswith("\n") else content + "\n"
                )

                with open(path, "w", encoding=encoding) as f:
                    f.writelines(lines)

                return {
                    "success": True,
                    "operation": operation,
                    "filepath": str(path),
                    "inserted_at_line": insert_pos + 1,
                }

            elif operation == "delete_lines":
                if not path.is_file():
                    return {"success": False, "error": "Not a file"}
                if start_line is None:
                    return {"success": False, "error": "start_line required"}

                with open(path, "r", encoding=encoding) as f:
                    lines = f.readlines()

                end = end_line or start_line
                # Delete lines (1-indexed)
                del lines[start_line - 1 : end]

                with open(path, "w", encoding=encoding) as f:
                    f.writelines(lines)

                return {
                    "success": True,
                    "operation": operation,
                    "filepath": str(path),
                    "deleted_lines": f"{start_line} to {end}",
                }

            elif operation == "merge_files":
                if not files:
                    return {"success": False, "error": "files array required"}

                merged_content = []
                for file_path in files:
                    file_p = self._validate_path(file_path)
                    if file_p.is_file():
                        with open(file_p, "r", encoding=encoding) as f:
                            merged_content.append(f.read())

                with open(path, "w", encoding=encoding) as f:
                    f.write("\n".join(merged_content))

                return {
                    "success": True,
                    "operation": operation,
                    "output_file": str(path),
                    "merged_files": len(files),
                }

            elif operation == "split_file":
                if not path.is_file():
                    return {"success": False, "error": "Not a file"}
                if chunk_size is None:
                    return {
                        "success": False,
                        "error": "chunk_size required (lines per chunk)",
                    }

                with open(path, "r", encoding=encoding) as f:
                    lines = f.readlines()

                chunks = [
                    lines[i : i + chunk_size] for i in range(0, len(lines), chunk_size)
                ]
                output_files = []

                for idx, chunk in enumerate(chunks):
                    chunk_path = path.parent / f"{path.stem}_part{idx + 1}{path.suffix}"
                    with open(chunk_path, "w", encoding=encoding) as f:
                        f.writelines(chunk)
                    output_files.append(str(chunk_path))

                return {
                    "success": True,
                    "operation": operation,
                    "source_file": str(path),
                    "chunks_created": len(chunks),
                    "output_files": output_files,
                }

            elif operation == "deduplicate_lines":
                if not path.is_file():
                    return {"success": False, "error": "Not a file"}

                with open(path, "r", encoding=encoding) as f:
                    lines = f.readlines()

                original_count = len(lines)
                unique_lines = list(dict.fromkeys(lines))  # Preserves order

                with open(path, "w", encoding=encoding) as f:
                    f.writelines(unique_lines)

                return {
                    "success": True,
                    "operation": operation,
                    "filepath": str(path),
                    "original_lines": original_count,
                    "unique_lines": len(unique_lines),
                    "duplicates_removed": original_count - len(unique_lines),
                }

            elif operation == "sort_lines":
                if not path.is_file():
                    return {"success": False, "error": "Not a file"}

                with open(path, "r", encoding=encoding) as f:
                    lines = f.readlines()

                sorted_lines = sorted(
                    lines, key=lambda x: x.lower() if not case_sensitive else x
                )

                with open(path, "w", encoding=encoding) as f:
                    f.writelines(sorted_lines)

                return {
                    "success": True,
                    "operation": operation,
                    "filepath": str(path),
                    "lines_sorted": len(sorted_lines),
                }

            elif operation == "reverse_lines":
                if not path.is_file():
                    return {"success": False, "error": "Not a file"}

                with open(path, "r", encoding=encoding) as f:
                    lines = f.readlines()

                with open(path, "w", encoding=encoding) as f:
                    f.writelines(reversed(lines))

                return {"success": True, "operation": operation, "filepath": str(path)}

            # ==================== SEARCH OPERATIONS ====================
            elif operation == "search":
                if not path.is_dir():
                    return {"success": False, "error": "Not a directory"}
                if not pattern:
                    return {"success": False, "error": "Pattern required"}

                results = []
                for item in path.rglob(pattern) if recursive else path.glob(pattern):
                    results.append(str(item))

                return {
                    "success": True,
                    "operation": operation,
                    "directory": str(path),
                    "pattern": pattern,
                    "results": results,
                    "count": len(results),
                }

            elif operation == "search_content":
                if not pattern:
                    return {"success": False, "error": "Pattern required"}

                all_matches = []
                search_path = path if path.is_dir() else path.parent

                for file_path in (
                    search_path.rglob("*") if recursive else search_path.glob("*")
                ):
                    if file_path.is_file():
                        matches = self._search_in_file(
                            file_path,
                            pattern,
                            regex=False,
                            case_sensitive=case_sensitive,
                        )
                        all_matches.extend(matches)

                return {
                    "success": True,
                    "operation": operation,
                    "pattern": pattern,
                    "matches": all_matches,
                    "total_matches": len(all_matches),
                    "files_with_matches": len(set(m["file"] for m in all_matches)),
                }

            elif operation == "search_regex":
                if not pattern:
                    return {"success": False, "error": "Pattern required"}

                all_matches = []
                search_path = path if path.is_dir() else path.parent

                for file_path in (
                    search_path.rglob("*") if recursive else search_path.glob("*")
                ):
                    if file_path.is_file():
                        matches = self._search_in_file(
                            file_path,
                            pattern,
                            regex=True,
                            case_sensitive=case_sensitive,
                        )
                        all_matches.extend(matches)

                return {
                    "success": True,
                    "operation": operation,
                    "pattern": pattern,
                    "matches": all_matches,
                    "total_matches": len(all_matches),
                }

            elif operation == "find_duplicates":
                if not path.is_dir():
                    return {"success": False, "error": "Not a directory"}

                hash_dict = {}
                for file_path in path.rglob("*") if recursive else path.glob("*"):
                    if file_path.is_file():
                        file_hash = self._calculate_hash(file_path, hash_algorithm)
                        if file_hash in hash_dict:
                            hash_dict[file_hash].append(str(file_path))
                        else:
                            hash_dict[file_hash] = [str(file_path)]

                duplicates = {k: v for k, v in hash_dict.items() if len(v) > 1}

                return {
                    "success": True,
                    "operation": operation,
                    "directory": str(path),
                    "duplicate_groups": duplicates,
                    "total_duplicate_files": sum(
                        len(v) - 1 for v in duplicates.values()
                    ),
                }

            # ==================== ARCHIVE OPERATIONS ====================
            elif operation == "zip_create":
                if not files and not path.is_dir():
                    return {
                        "success": False,
                        "error": "Provide files array or directory",
                    }

                zip_path = (
                    self._validate_path(destination)
                    if destination
                    else path.with_suffix(".zip")
                )

                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                    if files:
                        for file_str in files:
                            file_p = self._validate_path(file_str)
                            if file_p.exists():
                                zipf.write(file_p, file_p.name)
                    elif path.is_dir():
                        for file_p in path.rglob("*"):
                            if file_p.is_file():
                                zipf.write(file_p, file_p.relative_to(path))

                return {
                    "success": True,
                    "operation": operation,
                    "zip_file": str(zip_path),
                }

            elif operation == "zip_extract":
                if not path.is_file():
                    return {"success": False, "error": "Not a file"}

                extract_path = (
                    self._validate_path(destination) if destination else path.parent
                )

                with zipfile.ZipFile(path, "r") as zipf:
                    zipf.extractall(extract_path)
                    extracted = zipf.namelist()

                return {
                    "success": True,
                    "operation": operation,
                    "zip_file": str(path),
                    "extracted_to": str(extract_path),
                    "files_extracted": len(extracted),
                }

            elif operation == "zip_list":
                if not path.is_file():
                    return {"success": False, "error": "Not a file"}

                with zipfile.ZipFile(path, "r") as zipf:
                    files_info = [
                        {
                            "filename": info.filename,
                            "size": info.file_size,
                            "compressed_size": info.compress_size,
                            "date": f"{info.date_time[0]}-{info.date_time[1]:02d}-{info.date_time[2]:02d}",
                        }
                        for info in zipf.filelist
                    ]

                return {
                    "success": True,
                    "operation": operation,
                    "zip_file": str(path),
                    "contents": files_info,
                }

            elif operation == "tar_create":
                tar_path = (
                    self._validate_path(destination)
                    if destination
                    else path.with_suffix(".tar.gz")
                )
                mode = f"w:{compression}" if compression else "w:gz"

                with tarfile.open(tar_path, mode) as tar:
                    if files:
                        for file_str in files:
                            file_p = self._validate_path(file_str)
                            if file_p.exists():
                                tar.add(file_p, arcname=file_p.name)
                    elif path.is_dir():
                        tar.add(path, arcname=path.name)

                return {
                    "success": True,
                    "operation": operation,
                    "tar_file": str(tar_path),
                }

            elif operation == "tar_extract":
                if not path.is_file():
                    return {"success": False, "error": "Not a file"}

                extract_path = (
                    self._validate_path(destination) if destination else path.parent
                )

                with tarfile.open(path, "r:*") as tar:
                    tar.extractall(extract_path)
                    members = tar.getnames()

                return {
                    "success": True,
                    "operation": operation,
                    "tar_file": str(path),
                    "extracted_to": str(extract_path),
                    "files_extracted": len(members),
                }

            # ==================== HASH & COMPARISON ====================
            elif operation == "hash":
                if not path.is_file():
                    return {"success": False, "error": "Not a file"}

                file_hash = self._calculate_hash(path, hash_algorithm)

                return {
                    "success": True,
                    "operation": operation,
                    "filepath": str(path),
                    "algorithm": hash_algorithm,
                    "hash": file_hash,
                }

            elif operation == "verify_hash":
                if not path.is_file():
                    return {"success": False, "error": "Not a file"}
                if not expected_hash:
                    return {"success": False, "error": "expected_hash required"}

                file_hash = self._calculate_hash(path, hash_algorithm)
                matches = file_hash.lower() == expected_hash.lower()

                return {
                    "success": True,
                    "operation": operation,
                    "filepath": str(path),
                    "algorithm": hash_algorithm,
                    "calculated_hash": file_hash,
                    "expected_hash": expected_hash,
                    "verified": matches,
                }

            elif operation == "compare_files":
                if not destination:
                    return {
                        "success": False,
                        "error": "destination required for comparison",
                    }

                file1 = path
                file2 = self._validate_path(destination)

                if not file1.is_file() or not file2.is_file():
                    return {"success": False, "error": "Both paths must be files"}

                hash1 = self._calculate_hash(file1, hash_algorithm)
                hash2 = self._calculate_hash(file2, hash_algorithm)

                identical = hash1 == hash2

                return {
                    "success": True,
                    "operation": operation,
                    "file1": str(file1),
                    "file2": str(file2),
                    "identical": identical,
                    "hash1": hash1,
                    "hash2": hash2,
                }

            # ==================== CSV OPERATIONS ====================
            elif operation == "csv_read":
                if not path.is_file():
                    return {"success": False, "error": "Not a file"}

                with open(path, "r", encoding=encoding) as f:
                    reader = csv.DictReader(f, delimiter=delimiter)
                    rows = list(reader)

                return {
                    "success": True,
                    "operation": operation,
                    "filepath": str(path),
                    "rows": rows,
                    "row_count": len(rows),
                    "columns": list(rows[0].keys()) if rows else [],
                }

            elif operation == "csv_write":
                if not content:
                    return {"success": False, "error": "content (JSON array) required"}
                if not headers:
                    return {"success": False, "error": "headers required"}

                rows = json.loads(content) if isinstance(content, str) else content

                with open(path, "w", encoding=encoding, newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter)
                    writer.writeheader()
                    writer.writerows(rows)

                return {
                    "success": True,
                    "operation": operation,
                    "filepath": str(path),
                    "rows_written": len(rows),
                }

            elif operation == "csv_append":
                if not content:
                    return {"success": False, "error": "content required"}

                rows = json.loads(content) if isinstance(content, str) else content

                with open(path, "a", encoding=encoding, newline="") as f:
                    writer = csv.DictWriter(
                        f, fieldnames=rows[0].keys(), delimiter=delimiter
                    )
                    writer.writerows(rows)

                return {
                    "success": True,
                    "operation": operation,
                    "filepath": str(path),
                    "rows_appended": len(rows),
                }

            elif operation == "csv_filter":
                if not path.is_file():
                    return {"success": False, "error": "Not a file"}
                if not filter_column or not filter_value:
                    return {
                        "success": False,
                        "error": "filter_column and filter_value required",
                    }

                with open(path, "r", encoding=encoding) as f:
                    reader = csv.DictReader(f, delimiter=delimiter)
                    filtered_rows = [
                        row for row in reader if row.get(filter_column) == filter_value
                    ]

                return {
                    "success": True,
                    "operation": operation,
                    "filepath": str(path),
                    "filter": f"{filter_column} = {filter_value}",
                    "matching_rows": filtered_rows,
                    "match_count": len(filtered_rows),
                }

            # ==================== BATCH OPERATIONS ====================
            elif operation == "batch_rename":
                if not files or not pattern or not replacement:
                    return {
                        "success": False,
                        "error": "files, pattern, and replacement required",
                    }

                renamed = []
                for file_str in files:
                    file_p = self._validate_path(file_str)
                    if file_p.exists():
                        new_name = re.sub(pattern, replacement, file_p.name)
                        new_path = file_p.parent / new_name
                        file_p.rename(new_path)
                        renamed.append({"old": str(file_p), "new": str(new_path)})

                return {
                    "success": True,
                    "operation": operation,
                    "renamed_files": renamed,
                    "count": len(renamed),
                }

            elif operation == "batch_delete":
                if not files:
                    return {"success": False, "error": "files array required"}

                deleted = []
                for file_str in files:
                    file_p = self._validate_path(file_str)
                    if file_p.exists():
                        if file_p.is_dir():
                            shutil.rmtree(file_p)
                        else:
                            file_p.unlink()
                        deleted.append(str(file_p))

                return {
                    "success": True,
                    "operation": operation,
                    "deleted_files": deleted,
                    "count": len(deleted),
                }

            elif operation == "batch_move":
                if not files or not destination:
                    return {"success": False, "error": "files and destination required"}

                dest_dir = self._validate_path(destination)
                if not dest_dir.is_dir():
                    dest_dir.mkdir(parents=True, exist_ok=True)

                moved = []
                for file_str in files:
                    file_p = self._validate_path(file_str)
                    if file_p.exists():
                        new_path = dest_dir / file_p.name
                        shutil.move(str(file_p), str(new_path))
                        moved.append({"from": str(file_p), "to": str(new_path)})

                return {
                    "success": True,
                    "operation": operation,
                    "moved_files": moved,
                    "count": len(moved),
                }

            # ==================== ADVANCED OPERATIONS ====================
            elif operation == "create_symlink":
                if not destination:
                    return {"success": False, "error": "destination required"}

                target = self._validate_path(destination)
                path.symlink_to(target)

                return {
                    "success": True,
                    "operation": operation,
                    "symlink": str(path),
                    "target": str(target),
                }

            elif operation == "resolve_symlink":
                if not path.is_symlink():
                    return {"success": False, "error": "Not a symlink"}

                resolved = path.resolve()

                return {
                    "success": True,
                    "operation": operation,
                    "symlink": str(path),
                    "resolved": str(resolved),
                }

            elif operation == "temp_file":
                suffix = path.suffix if path.suffix else ".tmp"
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=suffix, delete=False, encoding=encoding
                ) as tmp:
                    if content:
                        tmp.write(content)
                    temp_path = tmp.name

                return {"success": True, "operation": operation, "temp_file": temp_path}

            elif operation == "base64_encode":
                if not path.is_file():
                    return {"success": False, "error": "Not a file"}

                with open(path, "rb") as f:
                    encoded = base64.b64encode(f.read()).decode("utf-8")

                return {
                    "success": True,
                    "operation": operation,
                    "filepath": str(path),
                    "base64": encoded,
                }

            elif operation == "base64_decode":
                if not content:
                    return {"success": False, "error": "base64 content required"}

                decoded = base64.b64decode(content)
                with open(path, "wb") as f:
                    f.write(decoded)

                return {
                    "success": True,
                    "operation": operation,
                    "filepath": str(path),
                    "bytes_written": len(decoded),
                }

            elif operation == "mimetype":
                if not path.is_file():
                    return {"success": False, "error": "Not a file"}

                mime_type, encoding_type = mimetypes.guess_type(str(path))

                return {
                    "success": True,
                    "operation": operation,
                    "filepath": str(path),
                    "mimetype": mime_type,
                    "encoding": encoding_type,
                }

            elif operation == "permissions_change":
                if not permissions:
                    return {
                        "success": False,
                        "error": "permissions required (e.g., '755')",
                    }

                mode = int(permissions, 8)
                path.chmod(mode)

                return {
                    "success": True,
                    "operation": operation,
                    "filepath": str(path),
                    "permissions": permissions,
                }

            elif operation == "detect_encoding":
                if not path.is_file():
                    return {"success": False, "error": "Not a file"}

                detected = self._detect_encoding(path)

                return {
                    "success": True,
                    "operation": operation,
                    "filepath": str(path),
                    "encoding": detected,
                }

            elif operation == "size":
                if not path.exists():
                    return {"success": False, "error": "Path not found"}

                if path.is_file():
                    size = path.stat().st_size
                else:
                    size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())

                return {
                    "success": True,
                    "operation": operation,
                    "filepath": str(path),
                    "size_bytes": size,
                    "size_human": self._human_readable_size(size),
                }

            elif operation == "count_lines":
                if not path.is_file():
                    return {"success": False, "error": "Not a file"}

                with open(path, "r", encoding=encoding, errors="ignore") as f:
                    line_count = sum(1 for _ in f)

                return {
                    "success": True,
                    "operation": operation,
                    "filepath": str(path),
                    "lines": line_count,
                }

            # ==================== FILE MANAGEMENT (from original) ====================
            elif operation == "delete":
                if not path.exists():
                    return {"success": False, "error": "Path not found"}

                if path.is_dir():
                    if recursive:
                        shutil.rmtree(path)
                    else:
                        path.rmdir()
                else:
                    path.unlink()

                return {"success": True, "operation": operation, "filepath": str(path)}

            elif operation == "copy":
                if not destination:
                    return {"success": False, "error": "destination required"}

                dest_path = self._validate_path(destination)

                if create_dirs:
                    dest_path.parent.mkdir(parents=True, exist_ok=True)

                if path.is_dir():
                    shutil.copytree(path, dest_path, dirs_exist_ok=overwrite)
                else:
                    shutil.copy2(path, dest_path)

                return {
                    "success": True,
                    "operation": operation,
                    "source": str(path),
                    "destination": str(dest_path),
                }

            elif operation == "move":
                if not destination:
                    return {"success": False, "error": "destination required"}

                dest_path = self._validate_path(destination)
                shutil.move(str(path), str(dest_path))

                return {
                    "success": True,
                    "operation": operation,
                    "source": str(path),
                    "destination": str(dest_path),
                }

            elif operation == "rename":
                if not destination:
                    return {
                        "success": False,
                        "error": "destination (new name) required",
                    }

                new_path = path.parent / destination
                path.rename(new_path)

                return {
                    "success": True,
                    "operation": operation,
                    "old_name": str(path),
                    "new_name": str(new_path),
                }

            elif operation == "mkdir":
                path.mkdir(parents=recursive, exist_ok=overwrite)
                return {"success": True, "operation": operation, "filepath": str(path)}

            elif operation == "exists":
                return {
                    "success": True,
                    "operation": operation,
                    "filepath": str(path),
                    "exists": path.exists(),
                    "is_file": path.is_file() if path.exists() else None,
                    "is_directory": path.is_dir() if path.exists() else None,
                }

            elif operation == "info":
                if not path.exists():
                    return {"success": False, "error": "Path not found"}

                return {
                    "success": True,
                    "operation": operation,
                    "info": self._get_file_info(path),
                }

            elif operation == "list":
                if not path.is_dir():
                    return {"success": False, "error": "Not a directory"}

                items = []
                for item in sorted(
                    path.iterdir(), key=lambda x: (not x.is_dir(), x.name)
                ):
                    item_info = {
                        "name": item.name,
                        "type": "directory" if item.is_dir() else "file",
                        "size": item.stat().st_size if item.is_file() else None,
                        "modified": datetime.fromtimestamp(
                            item.stat().st_mtime
                        ).isoformat(),
                    }

                    if pattern and item.is_file() and not item.match(pattern):
                        continue

                    items.append(item_info)

                return {
                    "success": True,
                    "operation": operation,
                    "filepath": str(path),
                    "items": items,
                    "count": len(items),
                }

            elif operation == "tree":
                if not path.is_dir():
                    return {"success": False, "error": "Not a directory"}

                tree_lines = self._directory_tree(path, max_depth or 3)

                return {
                    "success": True,
                    "operation": operation,
                    "directory": str(path),
                    "tree": "\n".join(tree_lines),
                }

            else:
                return {"success": False, "error": f"Unknown operation: {operation}"}

        except PermissionError as e:
            return {"success": False, "error": f"Permission denied: {str(e)}"}
        except FileNotFoundError as e:
            return {"success": False, "error": f"File not found: {str(e)}"}
        except json.JSONDecodeError as e:
            return {"success": False, "error": f"Invalid JSON: {str(e)}"}
        except Exception as e:
            return {"success": False, "error": f"Error: {str(e)}"}
