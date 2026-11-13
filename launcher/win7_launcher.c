/* Native launcher for the Windows 7 package. Does not use .NET.
   Sets WENJU_QT=5 and starts runtime\pythonw.exe app.py.
   UNICODE is defined by -municode. */
#include <windows.h>

static void quote(wchar_t *dst, size_t cap, const wchar_t *src) {
    size_t n = 0;
    int slashes = 0;
    if (n + 1 < cap) dst[n++] = L'"';
    for (; *src; ++src) {
        if (*src == L'\\') { slashes++; continue; }
        if (*src == L'"') {
            while (slashes-- >= 0 && n + 1 < cap) dst[n++] = L'\\';
            slashes = 0;
        } else {
            while (slashes-- > 0 && n + 1 < cap) dst[n++] = L'\\';
            slashes = 0;
        }
        if (n + 1 < cap) dst[n++] = *src;
    }
    while (slashes-- > 0 && n + 2 < cap) { dst[n++] = L'\\'; dst[n++] = L'\\'; }
    if (n + 1 < cap) dst[n++] = L'"';
    dst[n] = 0;
}

static int has_arg(const wchar_t *needle) {
    int argc = 0, found = 0;
    wchar_t **argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    if (!argv) return 0;
    for (int i = 1; i < argc; i++) if (lstrcmpW(argv[i], needle) == 0) found = 1;
    LocalFree(argv);
    return found;
}

static void write_utf16(const wchar_t *path, const wchar_t *text) {
    HANDLE file = CreateFileW(path, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) return;
    WORD bom = 0xFEFF;
    DWORD wrote = 0;
    WriteFile(file, &bom, 2, &wrote, NULL);
    WriteFile(file, text, (DWORD)(lstrlenW(text) * sizeof(wchar_t)), &wrote, NULL);
    CloseHandle(file);
}

static void add(wchar_t *dst, size_t cap, const wchar_t *src) {
    size_t n = lstrlenW(dst);
    if (n + 1 >= cap) return;
    lstrcpynW(dst + n, src, (int)(cap - n));
}

/* Shortcuts live in the user profile. No administrator, no HKLM.
   wsprintf is limited to 1024 characters, so the script is appended. */
static void install_shortcuts(const wchar_t *home, const wchar_t *exe) {
    if (has_arg(L"--no-shortcuts")) return;
    wchar_t vbs[MAX_PATH + 32], script[12000], line[1024];
    DWORD n = GetTempPathW(MAX_PATH, vbs);
    if (n == 0 || n >= MAX_PATH) return;
    lstrcpynW(vbs + n, L"wenju-shortcuts.vbs", 32);
    script[0] = 0;
    add(script, 12000, L"Set sh = CreateObject(\"WScript.Shell\")\r\nSet fso = CreateObject(\"Scripting.FileSystemObject\")\r\n");
    add(script, 12000, L"desk = sh.SpecialFolders(\"Desktop\")\r\nprog = sh.SpecialFolders(\"Programs\")\r\nOn Error Resume Next\r\n");
    if (has_arg(L"--uninstall-shortcuts")) {
        add(script, 12000, L"Set sa = CreateObject(\"Shell.Application\")\r\n");
        add(script, 12000, L"sa.NameSpace(desk).ParseName(\"\u6587\u77e9.lnk\").InvokeVerb(\"taskbarunpin\")\r\n");
        add(script, 12000, L"sa.NameSpace(desk).ParseName(\"\u6587\u77e9.lnk\").InvokeVerb(\"\u4ece\u4efb\u52a1\u680f\u53d6\u6d88\u56fa\u5b9a\")\r\n");
        add(script, 12000, L"fso.DeleteFile desk & \"\\\u6587\u77e9.lnk\", True\r\nfso.DeleteFile prog & \"\\\u6587\u77e9.lnk\", True\r\n");
        add(script, 12000, L"fso.DeleteFile prog & \"\\\u5378\u8f7d\u6587\u77e9.lnk\", True\r\n");
    } else {
        wsprintfW(line, L"exe = \"%s\"\r\nhome = \"%s\"\r\n", exe, home);
        add(script, 12000, line);
        add(script, 12000, L"Sub Make(path, args)\r\n Set sc = sh.CreateShortcut(path)\r\n sc.TargetPath = exe\r\n sc.Arguments = args\r\n");
        add(script, 12000, L" sc.WorkingDirectory = home\r\n sc.IconLocation = exe & \",0\"\r\n sc.Description = \"\u6587\u77e9\"\r\n sc.Save\r\nEnd Sub\r\n");
        add(script, 12000, L"Make desk & \"\\\u6587\u77e9.lnk\", \"\"\r\nMake prog & \"\\\u6587\u77e9.lnk\", \"\"\r\n");
        add(script, 12000, L"Make prog & \"\\\u5378\u8f7d\u6587\u77e9.lnk\", \"--uninstall-shortcuts\"\r\n");
        add(script, 12000, L"Set sa = CreateObject(\"Shell.Application\")\r\n");
        add(script, 12000, L"sa.NameSpace(desk).ParseName(\"\u6587\u77e9.lnk\").InvokeVerb(\"taskbarpin\")\r\n");
        add(script, 12000, L"sa.NameSpace(desk).ParseName(\"\u6587\u77e9.lnk\").InvokeVerb(\"\u9501\u5b9a\u5230\u4efb\u52a1\u680f\")\r\n");
    }
    write_utf16(vbs, script);
    wchar_t cmd[MAX_PATH + 40];
    lstrcpyW(cmd, L"wscript.exe //B //Nologo ");
    lstrcatW(cmd, vbs);
    STARTUPINFOW si; PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si)); si.cb = sizeof(si);
    ZeroMemory(&pi, sizeof(pi));
    if (CreateProcessW(NULL, cmd, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, NULL, &si, &pi)) {
        WaitForSingleObject(pi.hProcess, 15000);
        CloseHandle(pi.hThread); CloseHandle(pi.hProcess);
    }
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE prev, PWSTR cmdline, int show) {
    wchar_t home[MAX_PATH];
    DWORD len = GetModuleFileNameW(NULL, home, MAX_PATH);
    if (len == 0 || len >= MAX_PATH) return 1;
    wchar_t *slash = wcsrchr(home, L'\\');
    if (!slash) return 1;
    *slash = 0;
    /* The outer entry sits beside the folder. The inner exe sits inside it. */
    {
        wchar_t nested[MAX_PATH], inner[MAX_PATH];
        wsprintfW(nested, L"%s\\\u6587\u77e9\\runtime\\pythonw.exe", home);
        if (GetFileAttributesW(nested) != INVALID_FILE_ATTRIBUTES) {
            wsprintfW(inner, L"%s\\\u6587\u77e9", home);
            lstrcpyW(home, inner);
        }
    }
    if (has_arg(L"--uninstall-shortcuts")) {
        wchar_t self[MAX_PATH];
        GetModuleFileNameW(NULL, self, MAX_PATH);
        install_shortcuts(home, self);
        return 0;
    }

    wchar_t python[MAX_PATH], app[MAX_PATH];
    wsprintfW(python, L"%s\\runtime\\pythonw.exe", home);
    wsprintfW(app, L"%s\\app.py", home);
    if (GetFileAttributesW(python) == INVALID_FILE_ATTRIBUTES || GetFileAttributesW(app) == INVALID_FILE_ATTRIBUTES) {
        MessageBoxW(NULL, L"\u8BF7\u5148\u5B8C\u6574\u89E3\u538B\u6587\u77E9\u4FBF\u643A\u5305\uFF0C\u5E76\u4FDD\u7559 EXE \u65C1\u7684 runtime\u3001core \u548C\u7A0B\u5E8F\u6587\u4EF6\u3002", L"\u6587\u77E9", MB_ICONINFORMATION);
        return 1;
    }
    /* Only the Win7 tree ships runtime\qt5.txt. Win10/11 must keep PySide6. */
    {
        wchar_t marker[MAX_PATH];
        wsprintfW(marker, L"%s\\runtime\\qt5.txt", home);
        if (GetFileAttributesW(marker) != INVALID_FILE_ATTRIBUTES)
            SetEnvironmentVariableW(L"WENJU_QT", L"5");
    }
    {
        wchar_t branded[MAX_PATH];
        wsprintfW(branded, L"%s\\\u6587\u77e9.exe", home);
        install_shortcuts(home, branded);
    }

    wchar_t quoted_python[MAX_PATH * 2], quoted_app[MAX_PATH * 2];
    quote(quoted_python, sizeof(quoted_python) / sizeof(wchar_t), python);
    quote(quoted_app, sizeof(quoted_app) / sizeof(wchar_t), app);
    /* CPython skips the first token as the program name, so pythonw.exe must be argv[0]. */
    wchar_t args[32768];
    lstrcpynW(args, quoted_python, 32768);
    lstrcatW(args, L" ");
    lstrcatW(args, quoted_app);
    int argc = 0;
    wchar_t **argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    if (argv) {
        for (int i = 1; i < argc; i++) {
            wchar_t q[MAX_PATH * 2];
            quote(q, sizeof(q) / sizeof(wchar_t), argv[i]);
            if (lstrlenW(args) + lstrlenW(q) + 2 < 32768) {
                lstrcatW(args, L" ");
                lstrcatW(args, q);
            }
        }
        LocalFree(argv);
    }
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    ZeroMemory(&pi, sizeof(pi));
    if (!CreateProcessW(python, args, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, home, &si, &pi)) {
        wchar_t msg[256];
        wsprintfW(msg, L"\u65E0\u6CD5\u542F\u52A8\u6587\u77E9\u3002\u9519\u8BEF\u7801 %lu", GetLastError());
        MessageBoxW(NULL, msg, L"\u6587\u77E9", MB_ICONERROR);
        return 1;
    }
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return 0;
}
