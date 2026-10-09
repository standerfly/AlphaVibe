"""Finder 快速動作（Automator「服務」）產生器：把 photo_tool 的功能包成右鍵
動作與 ⌃⌘ 快速鍵。用 Automator 而不是「捷徑」，是因為「捷徑」的「執行 Shell
指令碼」每換一批檔案就會跳確認視窗（實測）。

文件結構照本機既有的 Automator 服務複製（`document.wflow` 範本）。
安裝：`python3 photo_tool.py tags install`
"""
import copy
import os
import plistlib
import shutil
import subprocess
import uuid

WORKFLOW_TEMPLATE = {'AMApplicationBuild': '534',
 'AMApplicationVersion': '2.10',
 'AMDocumentVersion': '2',
 'actions': [{'action': {'AMAccepts': {'Container': 'List',
                                       'Optional': True,
                                       'Types': ['com.apple.cocoa.string']},
                         'AMActionVersion': '2.0.3',
                         'AMApplication': ['Automator'],
                         'AMParameterProperties': {'COMMAND_STRING': {},
                                                   'CheckedForUserDefaultShell': {},
                                                   'inputMethod': {},
                                                   'shell': {},
                                                   'source': {}},
                         'AMProvides': {'Container': 'List', 'Types': ['com.apple.cocoa.string']},
                         'ActionBundlePath': '/System/Library/Automator/Run Shell Script.action',
                         'ActionName': 'Run Shell Script',
                         'ActionParameters': {'COMMAND_STRING': '@COMMAND@',
                                              'CheckedForUserDefaultShell': True,
                                              'inputMethod': 1,
                                              'shell': '/bin/zsh',
                                              'source': ''},
                         'BundleIdentifier': 'com.apple.RunShellScript',
                         'CFBundleVersion': '2.0.3',
                         'CanShowSelectedItemsWhenRun': False,
                         'CanShowWhenRun': True,
                         'Category': ['AMCategoryUtilities'],
                         'Class Name': 'RunShellScriptAction',
                         'InputUUID': '@UUID@',
                         'Keywords': ['Shell', 'Script', 'Command', 'Run', 'Unix'],
                         'OutputUUID': '@UUID@',
                         'UUID': '@UUID@',
                         'UnlocalizedApplications': ['Automator'],
                         'arguments': {'0': {'default value': 0,
                                             'name': 'inputMethod',
                                             'required': '0',
                                             'type': '0',
                                             'uuid': '0'},
                                       '1': {'default value': False,
                                             'name': 'CheckedForUserDefaultShell',
                                             'required': '0',
                                             'type': '0',
                                             'uuid': '1'},
                                       '2': {'default value': '',
                                             'name': 'source',
                                             'required': '0',
                                             'type': '0',
                                             'uuid': '2'},
                                       '3': {'default value': '',
                                             'name': 'COMMAND_STRING',
                                             'required': '0',
                                             'type': '0',
                                             'uuid': '3'},
                                       '4': {'default value': '/bin/sh',
                                             'name': 'shell',
                                             'required': '0',
                                             'type': '0',
                                             'uuid': '4'}},
                         'conversionLabel': 0,
                         'isViewVisible': 1,
                         'location': '309.000000:305.000000',
                         'nibPath': '/System/Library/Automator/Run Shell '
                                    'Script.action/Contents/Resources/Base.lproj/main.nib'},
              'isViewVisible': 1}],
 'connectors': {},
 'workflowMetaData': {'applicationBundleID': 'com.apple.finder',
                      'applicationBundleIDsByPath': {'/System/Library/CoreServices/Finder.app': 'com.apple.finder'},
                      'applicationPath': '/System/Library/CoreServices/Finder.app',
                      'applicationPaths': ['/System/Library/CoreServices/Finder.app'],
                      'inputTypeIdentifier': 'com.apple.Automator.fileSystemObject',
                      'outputTypeIdentifier': 'com.apple.Automator.nothing',
                      'presentationMode': 15,
                      'processesInput': False,
                      'serviceApplicationBundleID': 'com.apple.finder',
                      'serviceApplicationPath': '/System/Library/CoreServices/Finder.app',
                      'serviceInputTypeIdentifier': 'com.apple.Automator.fileSystemObject',
                      'serviceOutputTypeIdentifier': 'com.apple.Automator.nothing',
                      'serviceProcessesInput': False,
                      'systemImageName': 'NSActionTemplate',
                      'useAutomaticInputType': False,
                      'workflowTypeIdentifier': 'com.apple.Automator.servicesMenu'}}


def wrapper_script_path():
    return os.path.expanduser("~/.local/bin/photo-tool.sh")


def write_wrapper(repo_kb_mcp_dir):
    """寫出 ~/.local/bin/photo-tool.sh：Automator 的環境 PATH 很短，統一在
    這裡補上 homebrew 路徑並呼叫 photo_tool.py（路徑依實際安裝位置，所以
    換一台電腦 clone 之後重新執行 install 即可）。"""
    path = wrapper_script_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("#!/bin/zsh\n"
                "export PATH=/opt/homebrew/bin:/usr/local/bin:$PATH\n"
                'exec /usr/bin/python3 "' + repo_kb_mcp_dir + '/photo_tool.py" "$@"\n')
    os.chmod(path, 0o755)
    return path


def write_service(services_dir, name, command, file_type="public.item"):
    """建立一個 Finder 右鍵動作 `<name>.workflow`。"""
    contents = os.path.join(services_dir, name + ".workflow", "Contents")
    os.makedirs(contents, exist_ok=True)
    info = {"NSServices": [{
        "NSBackgroundColorName": "background", "NSIconName": "NSActionTemplate",
        "NSMenuItem": {"default": name}, "NSMessage": "runWorkflowAsService",
        "NSRequiredContext": {"NSApplicationIdentifier": "com.apple.finder"},
        "NSSendFileTypes": [file_type]}]}
    with open(os.path.join(contents, "Info.plist"), "wb") as f:
        plistlib.dump(info, f)
    wf = copy.deepcopy(WORKFLOW_TEMPLATE)
    action = wf["actions"][0]["action"]
    action["ActionParameters"]["COMMAND_STRING"] = command
    for key in ("InputUUID", "OutputUUID", "UUID"):
        action[key] = str(uuid.uuid4()).upper()
    with open(os.path.join(contents, "document.wflow"), "wb") as f:
        plistlib.dump(wf, f)


def service_specs(vocab):
    """依標籤清單算出要建立的動作：[(名稱, 指令, 快速鍵)]。"""
    cmd = '"' + wrapper_script_path() + '"'
    specs = []
    for t in vocab["tags"]:
        key = t.get("key")
        if key:
            specs.append(("相片標籤 " + key.upper() + " " + t["name"],
                          cmd + " tag-slot " + key + ' "$@"', key))
    specs.append(("相片貼標籤…", cmd + ' tag-picker "$@"', "t"))
    specs.append(("相片標籤速查表", cmd + ' tag-cheatsheet "$@"', "/"))
    specs.append(("相片管理標籤…", cmd + " tag-manager", "m"))
    return specs


def _is_ours(entry_name):
    return entry_name.startswith("相片標籤 ") or entry_name in ("相片貼標籤…", "相片標籤速查表", "相片管理標籤…")


def install(vocab, services_dir=None, bind=True):
    """重建所有標籤相關的右鍵動作與快速鍵（先清掉舊的同名前綴項目）。
    回傳建立的動作名稱清單。`bind=False` 時只寫檔案、不動系統設定（測試用）。"""
    services_dir = services_dir or os.path.expanduser("~/Library/Services")
    os.makedirs(services_dir, exist_ok=True)
    for entry in os.listdir(services_dir):
        if entry.endswith(".workflow") and _is_ours(entry[:-len(".workflow")]):
            shutil.rmtree(os.path.join(services_dir, entry), ignore_errors=True)
    specs = service_specs(vocab)
    for name, command, _key in specs:
        write_service(services_dir, name, command)
    if bind:
        _bind_keys([(n, k) for n, _c, k in specs])
    return [n for n, _c, _k in specs]


def _bind_keys(name_keys):
    pbs = os.path.expanduser("~/Library/Preferences/pbs.plist")
    buddy = "/usr/libexec/PlistBuddy"
    # 先刪掉所有舊的相片標籤動作設定（改名/換鍵後不留殘影）
    try:
        with open(pbs, "rb") as f:
            status = plistlib.load(f).get("NSServicesStatus", {})
    except (OSError, plistlib.InvalidFileException):
        status = {}
    for key in list(status):
        parts = key.split(" - ")
        if len(parts) >= 3 and _is_ours(parts[1]):
            subprocess.run([buddy, "-c", "Delete :NSServicesStatus:'" + key + "'", pbs],
                           capture_output=True)
    for name, key in name_keys:
        k = "(null) - " + name + " - runWorkflowAsService"
        base = "Add :NSServicesStatus:'" + k + "':"
        for c in (base + "key_equivalent string '^@" + key + "'",   # ^=Control @=Command
                  base + "presentation_modes:ContextMenu bool true",
                  base + "presentation_modes:ServicesMenu bool true",
                  base + "presentation_modes:FinderPreview bool true"):
            subprocess.run([buddy, "-c", c, pbs], capture_output=True)
    subprocess.run(["killall", "cfprefsd"], capture_output=True)
    subprocess.run(["/System/Library/CoreServices/pbs", "-flush"], capture_output=True)
    subprocess.run(["/System/Library/CoreServices/pbs", "-update"], capture_output=True)
