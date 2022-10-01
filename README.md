# nameer
A simple tool to rename video files based on their properties. Simply drag and drop a file onto the executable or supply arguments to it via a batch file.

## Requirements
You need to have `ffprobe.exe` in the directory or the system path. You can extract it from the extras directory in this repository.

### Example Input
`home recording.mkv`

### Example Output
`home_recording_h264_1080p_4263kbs_aac_2c_multi.mkv`

### Individual Parts

1. original file base name with underscores for spaces
2. video format
3. resolution
4. video bitrate
5. audio format (where available)
6. audio channels (where available)
6. audio bitrate (where available)
7. `multi` in case of multiple audio streams of same bitrate
8. language
9. original extension