# nameer
A simple tool to rename video files based on their properties. Simply drag and drop a file onto the executable or supply arguments to it via a batch file.

## Why
nameer exists for people with large video collections where it is not obvious what kind of settings and codecs were used for encoding/transmuxing. By putting those properties in file names, it gives users a better overview of the overall quality. This enables them to easily decide which files may need remastering.

### Requirements
You need to have `ffprobe.exe` in the directory or the system path. You can extract it from the extras directory in this repository.

### Example Input
`home recording.mkv`

### Example Output
`home_recording_hevc_1080p_23fps_3960kbs_aac_5.1ch_eng_cze.mkv`

### Individual Parts

1. original file base name with underscores for spaces
2. video format
3. resolution
4. frame rate
5. video bitrate
6. audio format (where applicable)
7. audio channels (where applicable)
8. audio bitrate (where applicable)
9. language (where applicable)
10. original extension