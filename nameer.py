import subprocess
import json
import os
import sys

def process_file(file):
    try:
        ffprobe_path = "ffprobe"  # Adjust this path if needed

        i_frame_command = [
            ffprobe_path, "-show_frames", file, "-read_intervals", "+%30", "-hide_banner"
        ]
        i_stdout = subprocess.run(i_frame_command, text=True, capture_output=True).stdout
        i_prob_count = i_stdout.count("pict_type=I")
        print(f"I frames found: {i_prob_count}")

        i_problem = "_problem" if i_prob_count < 3 else ""

        command_line = [
            ffprobe_path, "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_entries", "stream=bit_rate,codec_type,codec_name,height,channels,tags,r_frame_rate,index:stream_tags=language", file
        ]

        stdout = subprocess.run(command_line, text=True, capture_output=True).stdout
        json_all = json.loads(stdout)

        new_file_values = []
        accepted = ["video", "audio"]
        lang_tags = ["language", "LANGUAGE", "lang"]

        codec_to_tags = {
            "video": ["height", "r_frame_rate", "bit_rate"],
            "audio": ["channels", "bit_rate"]
        }

        for stream in json_all["streams"]:
            codec_type = stream["codec_type"]
            if codec_type in accepted:
                if stream["codec_name"].upper() not in new_file_values:
                    new_file_values.append(stream["codec_name"].upper())
                for tag in codec_to_tags[codec_type]:
                    if tag in stream:
                        value = stream[tag]
                        if tag == "r_frame_rate":
                            value = f"{int(eval(value))}fps"
                        elif tag == "bit_rate":
                            value = f"{int(int(value) / 1024)}kbs"
                        new_file_values.append(str(value))
                if codec_type == "video" and stream["index"] == 0:
                    new_file_values.append(f"{stream['height']}p")

            if codec_type == "audio":
                channels = stream['channels']
                if channels == 6:
                    channels = 5.1
                if f"{channels}ch" not in new_file_values:
                    new_file_values.append(f"{channels}ch")

            if "tags" in stream:
                for lang_tag in lang_tags:
                    if lang_tag in stream["tags"]:
                        if stream['tags'][lang_tag].lower() not in new_file_values:
                            new_file_values.append(stream['tags'][lang_tag].lower())

        if i_problem:
            new_file_values.append("i_frame_issue")

        new_file_values.insert(0, os.path.splitext(file)[0].replace(" ", "_"))
        output_file = "_".join(new_file_values) + os.path.splitext(file)[1]

        os.rename(file, output_file)
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    files = sys.argv[1:]
    for file in files:
        process_file(file)
