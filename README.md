# JSIDL to JSON

## Summary

Generates JSON schemes from JSIDL files. JSIDL stands for JAUS Service Interface Definition Language and contains also message definitions used to generate JSON scheme files.

This package contains no JSIDL files. You can find such files in [JausToolsSet][jts] or [ROS/IOP Bridge][ros_iop_bridge].

Example scheme for __QueryPlatformSpecifications__:

```json
{
  "name": "QueryPlatformSpecifications",
  "messageId": "2502",
  "isCommand": false,
  "description": "Request PlatformSpecifications data",
  "type": "object",
  "properties": {
    "HeaderRec": {
      "type": "object",
      "comment": "",
      "required": [
        "MessageID"
      ],
      "properties": {
        "MessageID": {
          "type": "string",
          "jausType": "unsigned short integer",
          "comment": "Two byte field to hold message ID",
          "const": "2502"
        }
      }
    }
  },
  "required": [
    "HeaderRec"
  ]
}
```

## Install

We use [PyXB-X](https://github.com/renalreg/PyXB-X) to generate python code for XMLSchema of JSIDL. Install dependencies:
```bash
pip install PyXB-X
```

For using as ROS1 package you need additionally
```bash
sudo apt install python3-catkin-pkg -y
```

Clone this repository to your preferred destination.

```bash
git clone https://github.com/fkie/iop-json-generator
```

### As ROS package inside ROS environment

If you use it with ROS put this repository into ROS workspace and call

```bash
colcon build --packages-select fkie_iop_json_generator --symlink-install 
```
or for ROS1
```bash
roscd && catkin build
```

### As standalone package

Use setup.py to install the code:

```bash
cd iop-json-generator/fkie_iop_json_generator
pip install . --break-system-packages
```

The executable **jsidl2json.py** is now located in `~/.local/bin`.

**Note:** to remove installed files call

```bash
pip uninstall fkie_iop_wireshark_plugin --break-system-packages
```

## Generate JSON schemes

Run **jsidl2json.py** to generate the JSON schemes.

In ROS environment you can do it by
```bash
ros2 run fkie_iop_json_generator jsidl2json.py
```

or (ROS1)

```bash
rosrun fkie_iop_json_generator jsidl2json.py
```

otherwise

```bash
python3 ~/.local/bin/jsidl2json.py
```

If no path for JSIDL files is given the script tries to find the `fkie_iop_builder` ROS package from [ROS/IOP Bridge][ros_iop_bridge].

You can change this path with `--input_path`.

By default, the schemes are written into `{cwd}/schemes` directory. You can change it by `--output_path`.

You can exclude subfolder from parsing if they contain different versions of the same message, e.g.

```bash
ros2 run fkie_iop_json_generator jsidl2json.py --exclude urn.jaus.jss.core-v1.0 --exclude urn.jaus.jss.manipulator  --input_path ~/tmp/jsidl --output_path ~/tmp/schemes -v
```

[iop]: https://en.wikipedia.org/wiki/UGV_Interoperability_Profile
[jts]: https://github.com/jaustoolset/jaustoolset
[ros_iop_bridge]: https://github.com/fkie/iop_core
[pyxb]: https://pypi.org/project/PyXB
