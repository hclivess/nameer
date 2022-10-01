import subprocess
import re
import json
import os
import sys

files = sys.argv[1:]
#files = ["a.mkv"]

for file in files:

    command_line = f'ffprobe.exe -v quiet -print_format json -show_format -show_entries stream=bit_rate,codec_type,codec_name,height,channels,tags,index:stream_tags=language "{file}"'
    base_name = os.path.splitext(file)[0]
    extension = os.path.splitext(file)[1]

    print(f"Base: {base_name}")
    print(f"Extension: {extension}")

    process = subprocess.Popen(command_line, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    stdout, stderr = process.communicate()
    return_code = process.returncode
    pid = process.pid
    process.wait()

    json_all = json.loads(stdout.decode())

    print(json_all)
    new_file_values = [base_name.replace(" ", "_")]
    accepted = ["video", "audio"]

    for stream in json_all["streams"]:
        if stream["codec_type"] in accepted:
            if stream["codec_name"] not in new_file_values:
                new_file_values.append(stream["codec_name"])
            elif "multi" not in new_file_values:
                new_file_values.append("multi")

        if stream["codec_type"] == "video":
            new_file_values.append(f"{stream['height']}p")
            new_file_values.append(f"{int((int(json_all['format']['bit_rate'])) / 1024)}kbs")

        if stream["codec_type"] == "audio":
            if "bit_rate" in stream and f"{int((int(stream['bit_rate'])) / 1024)}kbs" not in new_file_values:
                new_file_values.append(f"{int((int(stream['bit_rate'])) / 1024)}kbs")

            if f"{stream['channels']}c" not in new_file_values:
                new_file_values.append(f"{stream['channels']}c")

            if f"{stream['tags']['language']}" not in new_file_values:
                new_file_values.append(f"{stream['tags']['language']}")

    output_file = "_".join(new_file_values)
    output_file += extension

    os.rename(file, output_file)
