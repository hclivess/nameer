import subprocess
import re
import json
import os
import sys
import time

files = sys.argv[1:]
#files = ["normal.mkv"]

for file in files:

    """iframe check"""

    i_frame_command = f'ffprobe -show_frames "{file}" -read_intervals %+30 -hide_banner'
    with subprocess.Popen(i_frame_command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as i_frame_process:
        i_stdout, i_stderr = i_frame_process.communicate()
        i_return_code = i_frame_process.returncode
        i_pid = i_frame_process.pid
        i_frame_process.wait()

        i_out = str(i_stdout)
        i_prob_count = i_out.count("pict_type=I")
        print(f"I frames found: {i_prob_count}")

        if i_prob_count < 3:
            i_problem = "_problem"
        else:
            i_problem = ""
    """iframe check"""

    command_line = f'ffprobe.exe -v quiet -print_format json -show_format -show_entries stream=bit_rate,codec_type,codec_name,height,channels,tags,r_frame_rate,index:stream_tags=language "{file}"'
    base_name = os.path.splitext(file)[0]
    extension = os.path.splitext(file)[1]

    print(f"Base: {base_name}")
    print(f"Extension: {extension}")

    with subprocess.Popen(command_line, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as process:
        stdout, stderr = process.communicate()
        return_code = process.returncode
        pid = process.pid
        process.wait()

        print(stdout.decode())
        json_all = json.loads(stdout.decode())

    print(json_all)
    new_file_values = []
    accepted = ["video", "audio"]

    for stream in json_all["streams"]:
        if stream["codec_type"] in accepted:
            if stream["codec_name"].upper() not in new_file_values:
                new_file_values.append(stream["codec_name"].upper())

        if stream["codec_type"] == "video" and stream["index"] == 0:
            new_file_values.append(f"{stream['height']}p")

            frame_rate_str = stream['r_frame_rate'].split("/")
            frame_rate = int(int(frame_rate_str[0]) / int(frame_rate_str[1]))
            new_file_values.append(f"{frame_rate}fps")

            new_file_values.append(f"{int((int(json_all['format']['bit_rate'])) / 1024)}kbs")

        if stream["codec_type"] == "audio":
            channels = stream['channels']
            if channels == 6:
                channels = 5.1
            if f"{channels}ch" not in new_file_values:
                new_file_values.append(f"{channels}ch")

            if "bit_rate" in stream and f"{int((int(stream['bit_rate'])) / 1024)}kbs" not in new_file_values:
                new_file_values.append(f"{int((int(stream['bit_rate'])) / 1024)}kbs")

    lang_tags = ["language", "LANGUAGE", "lang"]
    for stream in json_all["streams"]:
        """tags at the end, only use tags for language because they are not tied to real values"""
        if stream["codec_type"] == "audio":
            if "tags" in stream:
                for lang_tag in lang_tags:
                    if lang_tag in stream["tags"]:
                        if f"{stream['tags'][lang_tag].lower()}" not in new_file_values:
                            new_file_values.append(f"{stream['tags'][lang_tag].lower()}")

    if i_problem:
        new_file_values.append("i_frame_issue")

    # new_file_values = [x.lower() for x in new_file_values]
    new_file_values.insert(0, base_name.replace(" ", "_"))

    output_file = "_".join(new_file_values)
    output_file += extension

    os.rename(file, output_file)
