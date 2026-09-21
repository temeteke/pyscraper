# Downloading Guide

`WebFile` (HTTP) and `HlsFile` (HLS) download to a temporary path and move the
result to the final `filepath` only once the transfer completes. The move uses
`shutil.move`: a rename on the same filesystem, and copy + delete across
filesystems (a failed cross-filesystem copy can leave a partial output file).

## Temporary paths

| Class | Temporary path | Default |
| --- | --- | --- |
| `WebFile.temp_file` | Partial download | `<filepath>.part` |
| `HlsFile.temp_file` | ffmpeg merge output | `.<filename>` (same directory as the output) |
| `HlsFile.temp_directory` | Segment/playlist scratch directory | `<directory>/<filestem>` |

`WebFile.tempfile` is a deprecated alias for `WebFile.temp_file`.

## Overriding temporary paths

`WebFile.download()` accepts `temp_file=`. `HlsFile.download()` accepts both
`temp_file=` and `temp_directory=`.

- Overrides are **local to the call**: they do not mutate the instance, so
  `WebFile.temp_file` / `HlsFile.temp_directory` keep returning the defaults.
- Values are used literally (no `~` expansion).
- Relative overrides resolve against the current working directory, not
  `directory`.
- A `temp_file` parent directory is not created automatically; `HlsFile`
  creates the `temp_directory` (including parents).
- `HlsFile` builds its segment `WebFile`s from the resolved `temp_directory`,
  so an earlier `exists()` call cannot pin a stale directory.

## Cleaning up

`unlink()` removes the final file and the default temporary paths. To remove a
custom path, pass the same value to `unlink()`:

```python
web_file.download(temp_file="partial.bin")
web_file.unlink(temp_file="partial.bin")

hls_file.download(temp_directory="scratch")
hls_file.unlink(temp_directory="scratch")
```

## `temp_directory` safety guard

`HlsFile.download()` removes `temp_directory` with `shutil.rmtree`, so a
`temp_directory` that is any of the following is rejected with `ValueError`:

- empty, `.`, `..`
- the current working directory or one of its ancestors
- the filesystem root
- the output file itself or one of its ancestors

Paths are compared after `resolve()` (symlinks and `..` normalized):
case-sensitive on POSIX and case-insensitive on Windows. Case-insensitive POSIX
filesystems (e.g. default macOS APFS) are not distinguished.

## Content-Disposition filename resolution

`WebFile.get_filename()` resolves the output name in this order:

1. `filename*` (RFC 5987): `charset'language'percent-encoded`, decoded with the
   declared charset (UTF-8 when the charset is omitted).
2. `filename` (quoted or unquoted; `;`-separated trailing parameters are not
   consumed).
3. The URL basename.

Directory components (both `/` and `\`) are stripped, so
`filename="C:\dir\a.mp4"` yields `a.mp4`. Empty, whitespace-only, `.`, `..`, or
values containing control characters are rejected and fall back to the URL
basename, as are malformed `filename*` values (no `'` charset/language
separator) and ones with an invalid percent-encoding or an undecodable charset.

`HlsFile` ignores `Content-Disposition` (it uses the URL stem plus a fixed
`.mp4` suffix).
