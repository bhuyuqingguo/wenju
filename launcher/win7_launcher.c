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

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE prev, PWSTR cmdline, int show) {
    wchar_t home[MAX_PATH];
    DWORD len = GetModuleFileNameW(NULL, home, MAX_PATH);
    if (len == 0 || len >= MAX_PATH) return 1;
    wchar_t *slash = wcsrchr(home, L'\\');
    if (!slash) return 1;
    *slash = 0;

    wchar_t python[MAX_PATH], app[MAX_PATH];
    wsprintfW(python, L"%s\\runtime\\pythonw.exe", home);
    wsprintfW(app, L"%s\\app.py", home);
    if (GetFileAttributesW(python) == INVALID_FILE_ATTRIBUTES || GetFileAttributesW(app) == INVALID_FILE_ATTRIBUTES) {
        MessageBoxW(NULL, L"\u8BF7\u5148\u5B8C\u6574\u89E3\u538B\u6587\u77E9\u4FBF\u643A\u5305\uFF0C\u5E76\u4FDD\u7559 EXE \u65C1\u7684 runtime\u3001core \u548C\u7A0B\u5E8F\u6587\u4EF6\u3002", L"\u6587\u77E9", MB_ICONINFORMATION);
        return 1;
    }
    SetEnvironmentVariableW(L"WENJU_QT", L"5");

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
