# Nameer: Simplifying Video File Renaming

**Nameer** is a utility that streamlines the renaming of video files by utilizing their properties. It supports both dragging and dropping files onto the executable and supplying arguments via batch files.

## Purpose

The primary aim of **Nameer** is to facilitate the organization and management of video collections. By embedding essential properties into filenames, users can easily gauge encoding, quality, and other attributes of their videos. This functionality empowers users to determine which files may require further attention or remastering.

## Requirements

To use **Nameer**, ensure that `ffprobe.exe` is present either in the tool's directory or within the system path. You can extract this executable from the "extras" directory in the **Nameer** repository.

## Usage Example

**Input:**

Original Filename: `home recording.mkv`

**Output:**

Renamed Filename: `home_recording_H264_1040p_23fps_5819kbs_AAC_2ch_eng_cze.mkv`

## Components in Renamed Filenames

1. Original file base name with underscores for spaces
2. Video format
3. Resolution
4. Frame rate
5. Video bitrate
6. Audio format (if applicable)
7. Audio channels (if applicable)
8. Audio bitrate (if applicable)
9. Language (if applicable)
10. Original extension

By following these guidelines, **Nameer** provides a structured approach to renaming video files, enhancing users' ability to manage and comprehend the properties of their collection.
