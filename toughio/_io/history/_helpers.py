from ..._common import filetype_from_filename, register_format

__all__ = [
    "register",
    "read",
    "write",
]


_extension_to_filetype = {}
_reader_map = {}
_writer_map = {}


def register(file_format, extensions, reader, writer=None):
    """
    Register a new history format.

    Parameters
    ----------
    file_format : str
        File format to register.
    extensions : array_like
        List of extensions to associate to the new format.
    reader : callable
        Read function.
    writer : callable or None, optional, default None
        Write function.

    """
    register_format(
        fmt=file_format,
        ext_to_fmt=_extension_to_filetype,
        reader_map=_reader_map,
        writer_map=_writer_map,
        extensions=extensions,
        reader=reader,
        writer=writer,
    )


def read(filename, file_format=None, **kwargs):
    """
    Read history file.

    Parameters
    ----------
    filename : str, pathlike or buffer
        Input file name or buffer.
    file_format : str or None, optional, default None
        Input file format.

    Returns
    -------
    dict
        History data.

    """
    if not (file_format is None or file_format in _reader_map):
        raise ValueError()

    file_format = _get_file_format(filename, file_format)
    return _reader_map[file_format](filename, **kwargs)


def _get_file_format(filename, file_format):
    """Get file format."""
    if not file_format:
        file_format = filetype_from_filename(filename, _extension_to_filetype)

    if not file_format:
        file_format = "csv"

    return file_format
