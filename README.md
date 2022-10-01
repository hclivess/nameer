# nameer
A simple tool to rename video files based on their properties. Simply drag and drop a file onto the executable or supply arguments to it via a batch file.

## Requirements
You need to have `ffprobe.exe` in the directory or the system path. You can extract it from the extras directory in this repository.

### Example Input
`recording.mkv`

### Example Output
`recording_mpeg4_272p_561kbs_mp3_156kbs.mkv`

### Individual Parts

- original filename
- video format
- resolution
- video bitrate
- audio format
- audio bitrate
- original extension