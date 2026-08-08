import gzip
import os
import shutil
import string
import random
import sqlite3

import pandas as pd
import pickle as pkl

from io import BytesIO
from pathlib import Path
from typing import Union, List

# Set by the Electron shell. On the desktop the data is already on this machine,
# so files are referenced where they lie instead of being copied into the cache:
# MS runs are routinely gigabytes and copying doubles disk use for no benefit.
DESKTOP = os.environ.get("FLASHAPP_DESKTOP") == "1"


def safe_component(value: str, what: str = "name") -> str:
    """A dataset id or file name that is safe to join onto a directory.

    Dataset ids are derived from user-supplied filenames, and on the hosted
    deployment the filename arrives straight from a multipart request, which
    Streamlit does not sanitise. Both are joined into
    <cache>/files/<dataset_id>/<file_name> and the directory is later rmtree'd,
    so a value containing ".." or a separator writes and deletes outside the
    cache entirely. Verified: store_file("../../..", …, file_name="victim.txt")
    overwrote a file three levels up before this guard existed.

    Rejects rather than sanitises: a silently rewritten dataset id would break
    the filename-based grouping the upload pages depend on.
    """
    text = str(value)
    if not text or text in (".", ".."):
        raise ValueError(f"unsafe {what}: {value!r}")
    # "/" and NUL are never legal in a component. Backslash is a separator on
    # Windows but a legal filename character on POSIX, so rejecting it outright
    # would refuse real files on macOS and Linux — reject it only where the OS
    # would actually treat it as a separator.
    separators = {"/", os.sep, os.altsep} - {None}
    if "\0" in text or any(sep in text for sep in separators):
        raise ValueError(f"unsafe {what}: {value!r}")
    if Path(text).name != text or Path(text).is_absolute():
        raise ValueError(f"unsafe {what}: {value!r}")
    return text


def _identifier(name: str) -> str:
    """Validate a SQL table or column name that has to be interpolated.

    Values are bound as parameters, but SQLite cannot parameterise identifiers,
    and this schema creates columns at runtime from caller-supplied name tags.
    Rather than quote-and-hope, anything that is not a plain identifier is
    rejected outright — the tags are all code constants, so a rejection is a
    programming error, not user input.
    """
    name = str(name)
    if not name or not (name[0].isalpha() or name[0] == "_"):
        raise ValueError(f"unsafe SQL identifier: {name!r}")
    if not all(c.isalnum() or c == "_" for c in name):
        raise ValueError(f"unsafe SQL identifier: {name!r}")
    return name


class FileManager:
    """
    Manages file paths for operations such as changing file extensions, organizing files
    into result directories, and handling file collections for processing tools. Designed
    to be flexible for handling both individual files and lists of files, with integration
    into a Streamlit workflow.

    Methods:
        get_files: Returns a list of file paths as strings for the specified files, optionally with new file type and results subdirectory.
        collect: Collects all files in a single list (e.g. to pass to tools which can handle multiple input files at once).
    """

    def __init__(
        self,
        workflow_dir: Path,
        cache_path: Path,
    ):
        """
        Initializes the FileManager object with a the current workflow results directory.
        """
        self.workflow_dir = workflow_dir

        # Setup Caching
        self.cache_path = cache_path
        Path(self.cache_path, 'files').mkdir(parents=True, exist_ok=True)
        self._connect_to_sql()
        
    def _connect_to_sql(self):
        self.cache_connection = sqlite3.connect(
            Path(self.cache_path, 'cache.db'), isolation_level=None
        )
        self.cache_cursor = self.cache_connection.cursor()
        self.cache_cursor.execute("""
                          CREATE TABLE IF NOT EXISTS stored_data (
                            id TEXT PRIMARY KEY
                          );
        """)
        self.cache_cursor.execute("""
                          CREATE TABLE IF NOT EXISTS stored_files (
                            id TEXT PRIMARY KEY
                          );
        """)

    def __getstate__(self):
        state = self.__dict__.copy()
        del state['cache_connection']
        del state['cache_cursor']
        return state
    
    def __setstate__(self, state):
        self.__dict__.update(state)
        self._connect_to_sql()

    def get_files(
        self,
        files: Union[List[Union[str, Path]], Path, str, List[List[str]]],
        set_file_type: str = None,
        set_results_dir: str = None,
        collect: bool = False,
    ) -> Union[List[str], List[List[str]]]:
        """
        Returns a list of file paths as strings for the specified files.
        Otionally sets or changes the file extension for all files to the
        specified file type and changes the directory to a new subdirectory
        in the workflow results directory.

        Args:
            files (Union[List[Union[str, Path]], Path, str, List[List[str]]]): The list of file
            paths to change the type for.
            set_file_type (str): The file extension to set for all files.
            set_results_dir (str): The name of a subdirectory in the workflow
            results directory to change to. If "auto" or "" a random name will be generated.
            collect (bool): Whether to collect all files into a single list. Will return a list
            with a single entry, which is a list of all files. Useful to pass to tools which
            can handle multiple input files at once.

        Returns:
            Union[List[str], List[List[str]]]: The (modified) files list.
        """
        # Handle input single string
        if isinstance(files, str):
            files = [files]
        # Handle input single Path object, can be directory or file
        elif isinstance(files, Path):
            if files.is_dir():
                files = [str(f) for f in files.iterdir()]
            else:
                files = [str(files)]
        # Handle input list
        elif isinstance(files, list) and files:
            # Can have one entry of strings (e.g. if has been collected before by FileManager)
            if isinstance(files[0], list):
                files = files[0]
            # Make sure ever file path is a string
            files = [str(f) for f in files if isinstance(f, Path) or isinstance(f, str)]
        # Raise error if no files have been detected
        if not files:
            raise ValueError(
                f"No files found, can not set file type **{set_file_type}**, results_dir **{set_results_dir}** and collect **{collect}**."
            )
        # Set new file type if required
        if set_file_type is not None:
            files = self._set_type(files, set_file_type)
        # Set new results subdirectory if required
        if set_results_dir is not None:
            if set_results_dir == "auto":
                set_results_dir = ""
            files = self._set_dir(files, set_results_dir)
        # Collect files into a single list if required
        if collect:
            files = [files]
        return files

    def _set_type(self, files: List[str], set_file_type: str) -> List[str]:
        """
        Sets or changes the file extension for all files in the collection to the
        specified file type.

        Args:
            files (List[str]): The list of file paths to change the type for.
            set_file_type (str): The file extension to set for all files.

        Returns:
            List[str]: The files list with new type.
        """

        def change_extension(file_path, new_ext):
            return Path(file_path).with_suffix("." + new_ext)

        for i in range(len(files)):
            if isinstance(files[i], list):  # If the item is a list
                files[i] = [
                    str(change_extension(file, set_file_type)) for file in files[i]
                ]
            elif isinstance(files[i], str):  # If the item is a string
                files[i] = str(change_extension(files[i], set_file_type))
        return files

    def _set_dir(self, files: List[str], subdir_name: str) -> List[str]:
        """
        Sets the subdirectory within the results directory to store files. If the
        subdirectory name is 'auto' or empty, generates a random subdirectory name.
        Warns and overwrites if the subdirectory already exists.

        Args:
            files (List[str]): The list of file paths to change the type for.
            subdir_name (str): The name of the subdirectory within the results directory.

        Returns:
            List[str]: The files list with new directory.
        """
        if not subdir_name:
            subdir_name = self._create_results_sub_dir(subdir_name)
        else:
            subdir_name = self._create_results_sub_dir(subdir_name)

        def change_subdir(file_path, subdir):
            return Path(subdir, Path(file_path).name)

        for i in range(len(files)):
            if isinstance(files[i], list):  # If the item is a list
                files[i] = [str(change_subdir(file, subdir_name)) for file in files[i]]
            elif isinstance(files[i], str):  # If the item is a string
                files[i] = str(change_subdir(files[i], subdir_name))
        return files

    def _generate_random_code(self, length: int) -> str:
        """Generate a random code of the specified length.

        Args:
            length (int): Length of the random code.

        Returns:
            str: Random code of the specified length.
        """
        # Define the characters that can be used in the code
        # Includes both letters and numbers
        characters = string.ascii_letters + string.digits

        # Generate a random code of the specified length
        random_code = "".join(random.choice(characters) for _ in range(length))

        return random_code

    def _create_results_sub_dir(self, name: str = "") -> str:
        """
        Creates a subdirectory within the results directory for storing files. If the
        name is not specified or empty, generates a random name for the subdirectory.

        Args:
            name (str, optional): The desired name for the subdirectory.

        Returns:
            str: The path to the created subdirectory as a string.
        """
        # create a directory (e.g. for results of a TOPP tool) within the results directory
        # if name is empty string, auto generate a name
        if not name:
            name = self._generate_random_code(4)
            # make sure the subdirectory does not exist in results yet
            while Path(self.workflow_dir, "results", name).exists():
                name = self._generate_random_code(4)
        path = Path(self.workflow_dir, "results", name)
        path.mkdir(exist_ok=True)
        return str(path)
    
    def _get_column_list(self, table_name: str) -> List[str]:
        """
        Get a list of columns in the table.

        Args:
            table_name (str): The name of the table.

        Returns:
            columns (List): The columns in the table.
        """
        self.cache_cursor.execute(f"PRAGMA table_info({table_name});")
        return [col[1] for col in self.cache_cursor.fetchall()]

    
    def _add_column(self, table_name: str, column_name: str) -> None:
        """
        Checks if a column is in the cache table and if it is not adds 
        it to the table.

        Args:
            table_name (str): The name of the table
            column_name (str): The name of the column
        """

        # Fetch list of columns
        columns = self._get_column_list(table_name)

        # Add column to table if it does not exist
        if column_name not in columns:
            self.cache_cursor.execute(
                f"ALTER TABLE {table_name} ADD COLUMN {_identifier(column_name)} TEXT;"
            )

    def _add_entry(self, table_name: str, dataset_id: str, 
                   column_name: str, path: str) -> None:
        """
        Adds an entry to the cache index.

        Args:
            table_name (str): The name of the table
            dataset_id (str): The name of the dataset the data is 
                attached to.
            column_name (str): The name of the column
            path (str): The path to be inserted
        """

        # Ensure column exists
        self._add_column(table_name, column_name)

        # Store reference. dataset_id and path are user-derived — a filename
        # containing a quote used to break every later query against the
        # workspace, permanently and unrecoverably from inside the app.
        col = _identifier(column_name)
        self.cache_cursor.execute(f"""
            INSERT INTO {_identifier(table_name)} (id, {col})
            VALUES (?, ?)
            ON CONFLICT(id)
            DO UPDATE SET {col} = excluded.{col};
        """, (str(dataset_id), str(path)))

    def _store_data(self, dataset_id: str, name_tag: str, data) -> None:
        """
        Stores data as a cached file. Pandas DataFrames are stored as 
        parquet files, while all other data structures are stored as
        compressed pickle.
        Args:
            dataset_id (str): The name of the dataset the data is 
                attached to.
            name_tag (str): The name of the associated data structure.
            data: Any pickleable data structure.

        Returns:
            file_path (Path): The file path of the stored file.
        """
        
        path = Path(self.cache_path, 'files', dataset_id)
        path.mkdir(parents=True, exist_ok=True)
        
        # DataFrames are stored as apache parquet
        if isinstance(data, pd.DataFrame):
            path = Path(path, f"{name_tag}.pq")
            with open(path, 'wb') as f:
                data.to_parquet(f)
        # Other data structures are stored as compressed pickle
        else:
            path = Path(path, f"{name_tag}.pkl.gz")
            with gzip.open(path, 'wb') as f:
                pkl.dump(data, f)

        return path

    def store_data(self, dataset_id: str, name_tag: str, data) -> None:
        """
        Stores a given data structure.

        Args:
            dataset_id (str): The name of the dataset the data is 
                attached to.
            name_tag (str): The name of the associated data structure.
            data: Any pickleable data structure.
        """

        # Store datastructure as file
        data_path = self._store_data(dataset_id, name_tag, data)

        # Store reference in index
        self._add_entry('stored_data', dataset_id, name_tag, data_path)
        
    def _is_ours(self, path: Path) -> bool:
        """Does this file live inside storage we created and may delete?

        Anything under the workflow directory or the cache is ours; anything
        else belongs to the user and is never unlinked.
        """
        try:
            resolved = Path(path).resolve()
        except OSError:
            return False
        for root in (self.workflow_dir, self.cache_path):
            try:
                resolved.relative_to(Path(root).resolve())
                return True
            except (ValueError, OSError):
                continue
        return False

    def store_file(self, dataset_id: str, name_tag: str, file: Path | BytesIO,
                   remove: bool = True, file_name = None, link: bool = None) -> None:
        """
        Stores a given file.

        Args:
            dataset_id (str): The name of the dataset the data is 
                attached to.
            name_tag (str): The name of the associated data structure.
            file (Path of File-Like): The file that should be stored.
            remove (bool): Wether or not the file should be removed
                after copying it.
            filetype (str): The file extension of the file. Only
                neccessary if a file-like object is used as input.
            link (bool): Reference the file where it is instead of copying it
                into the cache. Defaults to True on the desktop app for real
                paths. A linked file is never removed, whatever `remove` says —
                it belongs to the user, not to the workspace.
        """
        # Ownership, not type. Inferring link from "is it a Path on desktop"
        # linked the workflow's own outputs, which live in a per-run temp
        # directory that Workflow.py deletes moments later — leaving index rows
        # pointing at deleted files. Only a call site that knows the file
        # belongs to the user may ask for linking.
        if link is None:
            link = False

        if link:
            # remove_results()/clear_cache() only delete inside cache_path, so a
            # linked original is never touched by deleting the dataset.
            self._add_entry('stored_files', dataset_id, name_tag, Path(file).resolve())
            return

        # Define storage path.
        # Not file.suffix: Streamlit's UploadedFile subclasses BytesIO and has
        # no .suffix, so reading it here — before the file-like branch below —
        # raised AttributeError for every browser upload, which is the only
        # path all three "manual result upload" pages use.
        dataset_id = safe_component(dataset_id, "dataset id")
        if file_name is None:
            suffix = Path(getattr(file, "name", "")).suffix if not isinstance(file, Path) else file.suffix
            file_name = f"{name_tag}{suffix}"
        file_name = safe_component(file_name, "file name")
        
        target_path = Path(
                self.cache_path, 'files', dataset_id, file_name
        )
        target_path.parent.mkdir(parents=True, exist_ok=True)

        # Store file in path
        if isinstance(file, BytesIO):
            with open(target_path, 'wb') as f:
                f.write(file.getbuffer())
        else:
            file = Path(file)
            shutil.copy(file, target_path)
            # remove=True means "this was our scratch copy, tidy it up". It must
            # never mean "delete the user's data". Callers pass user-chosen
            # paths here — the desktop file picker does — so ownership is
            # checked here rather than trusted from the call site.
            if remove and self._is_ours(file):
                file.unlink()

        # Store reference in index
        self._add_entry('stored_files', dataset_id, name_tag, target_path)

    def get_results_list(self, name_tags: List[str], partial=False) -> List[str]:
        """
        Get all results that contain data for specified fields.

        Args:
            name_tags (List): the fields to be considered.
        """
        # Some columns might not have been created yet (or ever)..
        available_columns = (
            set(self._get_column_list('stored_data')) 
            | set(self._get_column_list('stored_files'))
        )
        name_tags = [n for n in name_tags if n in available_columns]
        if len(name_tags) == 0:
            return []
        
        # Fetch data
        selection_operator = 'OR' if partial else 'AND'
        selection_statement = (
            f" IS NOT NULL {selection_operator} ".join(name_tags)
            + " IS NOT NULL;"
        )
        self.cache_cursor.execute(f"""
            SELECT id
            FROM (
                SELECT sd.id AS id, sd.*, sf.*
                FROM stored_data sd
                LEFT JOIN stored_files sf ON sd.id = sf.id

                UNION

                SELECT sf.id AS id, sd.*, sf.*
                FROM stored_files sf
                LEFT JOIN stored_data sd ON sf.id = sd.id
            ) combined
            WHERE {selection_statement}
        """)

        return [row[0] for row in self.cache_cursor.fetchall()]
    
    def get_results(self, dataset_id, name_tags, partial=False):
        results = {}
        # Retrieve files as Path objects
        file_columns = self._get_column_list('stored_files')
        file_columns = [c for c in file_columns if c in name_tags]
        if len(file_columns) > 0:
            self.cache_cursor.execute(f"""
                SELECT {', '.join(_identifier(c) for c in file_columns)}
                FROM stored_files
                WHERE id = ?;
            """, (str(dataset_id),))
            result = self.cache_cursor.fetchone()
            for c, r in zip(file_columns, result):
                if r is None:
                    if partial:
                        continue
                    else:
                        raise KeyError(f"{c} does not exist for {dataset_id}")
                results[c] = Path(r)
        # Retrieve data as Python objects
        data_columns = self._get_column_list('stored_data')
        data_columns = [c for c in data_columns if c in name_tags]
        if len(data_columns) > 0:
            self.cache_cursor.execute(f"""
                SELECT {', '.join(_identifier(c) for c in data_columns)}
                FROM stored_data
                WHERE id = ?;
            """, (str(dataset_id),))
            result = self.cache_cursor.fetchone()
            for c, r in zip(data_columns, result):
                if r is None:
                    if partial:
                        continue
                    else:
                        raise KeyError(f"{c} does not exist for {dataset_id}")
                file_path = Path(r)
                if file_path.suffix == '.pq':
                    data = pd.read_parquet(file_path)
                else:
                    with gzip.open(file_path, 'rb') as f:
                        data = pkl.load(f)
                results[c] = data
        return results
    
    def result_exists(self, dataset_id, name_tag):
        
        # Check which table is correct
        if name_tag in self._get_column_list('stored_data'):
            table = 'stored_data'
        elif name_tag in self._get_column_list('stored_files'):
            table = 'stored_files'
        else:
            return False
        
        # Check if field value is set
        self.cache_cursor.execute(f"""
            SELECT {_identifier(name_tag)}
            FROM {_identifier(table)}
            WHERE id = ? AND {_identifier(name_tag)} IS NOT NULL
        """, (str(dataset_id),))
        if self.cache_cursor.fetchone():
            return True
        return False

    def remove_results(self, dataset_id):
    
        # Remove references
        self.cache_cursor.execute(f"""
            DELETE FROM stored_data
            WHERE id = ?;
        """, (str(dataset_id),))
        self.cache_cursor.execute(f"""
            DELETE FROM stored_files
            WHERE id = ?;
        """, (str(dataset_id),))

        # Remove stored files. A dataset whose files are all linked has no
        # directory here at all, so this must tolerate its absence.
        # safe_component: this path is rmtree'd, so a ".." id would delete
        # outside the cache.
        shutil.rmtree(Path(self.cache_path, 'files', safe_component(dataset_id, 'dataset id')),
                      ignore_errors=True)

    def clear_cache(self):
        shutil.rmtree(Path(self.cache_path, 'files'))
        Path(self.cache_path, 'files').mkdir()
        self.cache_cursor.execute(f"DROP TABLE IF EXISTS stored_data;")
        self.cache_cursor.execute(f"DROP TABLE IF EXISTS stored_files;")
        self.cache_cursor.execute("""
                          CREATE TABLE IF NOT EXISTS stored_data (
                            id TEXT PRIMARY KEY
                          );
        """)
        self.cache_cursor.execute("""
                          CREATE TABLE IF NOT EXISTS stored_files (
                            id TEXT PRIMARY KEY
                          );
        """)

