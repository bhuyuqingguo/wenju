#define UNICODE
#define _UNICODE
#define NOMINMAX
#include <windows.h>
#include <shlobj.h>
#include <propkey.h>
#include <string>
#include <vector>

static const wchar_t AppId[] = L"WenJu.Desktop";
static const wchar_t Name[] = L"\u6587\u77e9";

static std::wstring quote(const std::wstring& value) {
    std::wstring out = L"\"";
    size_t slashes = 0;
    for (wchar_t ch : value) {
        if (ch == L'\\') { ++slashes; continue; }
        out.append(ch == L'"' ? 2 * slashes + 1 : slashes, L'\\');
        slashes = 0;
        out += ch;
    }
    out.append(2 * slashes, L'\\');
    return out + L'"';
}

static bool file_exists(const std::wstring& path) {
    DWORD flags = GetFileAttributesW(path.c_str());
    return flags != INVALID_FILE_ATTRIBUTES && !(flags & FILE_ATTRIBUTE_DIRECTORY);
}

static bool transient_path(const std::wstring& path) {
    wchar_t temp[32768];
    DWORD n = GetTempPathW(32768, temp);
    return n && n < 32768 && _wcsnicmp(path.c_str(), temp, n) == 0;
}

static HRESULT shortcut(int folder, const std::wstring& exe, const std::wstring& directory, bool create) {
    wchar_t base[MAX_PATH];
    HRESULT hr = SHGetFolderPathW(nullptr, folder, nullptr, SHGFP_TYPE_CURRENT, base);
    if (FAILED(hr)) return hr;
    std::wstring path = std::wstring(base) + L"\\" + Name + L".lnk";
    if (!create && !file_exists(path)) return S_FALSE;
    IShellLinkW* link = nullptr;
    hr = CoCreateInstance(CLSID_ShellLink, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&link));
    if (FAILED(hr)) return hr;
    IPersistFile* persist = nullptr;
    IPropertyStore* store = nullptr;
    hr = link->QueryInterface(IID_PPV_ARGS(&persist));
    if (SUCCEEDED(hr) && file_exists(path)) {
        hr = persist->Load(path.c_str(), STGM_READ);
        if (SUCCEEDED(hr)) {
            wchar_t old[MAX_PATH] = {};
            hr = link->GetPath(old, MAX_PATH, nullptr, SLGP_RAWPATH);
            const wchar_t* leaf = wcsrchr(old, L'\\');
            if (SUCCEEDED(hr) && (!leaf || (_wcsicmp(leaf+1, L"\u6587\u77e9.exe") && _wcsicmp(leaf+1, L"\u6253\u5f00\u6587\u77e9.exe"))))
                hr = HRESULT_FROM_WIN32(ERROR_ALREADY_EXISTS);
        }
    }
    if (SUCCEEDED(hr)) hr = link->SetPath(exe.c_str());
    if (SUCCEEDED(hr)) hr = link->SetWorkingDirectory(directory.c_str());
    if (SUCCEEDED(hr)) hr = link->SetIconLocation(exe.c_str(), 0);
    if (SUCCEEDED(hr)) hr = link->SetDescription(Name);
    if (SUCCEEDED(hr)) hr = link->SetArguments(L"");
    if (SUCCEEDED(hr)) hr = link->QueryInterface(IID_PPV_ARGS(&store));
    if (SUCCEEDED(hr)) {
        PROPVARIANT id = {};
        id.vt = VT_LPWSTR;
        id.pwszVal = const_cast<wchar_t*>(AppId);
        hr = store->SetValue(PKEY_AppUserModel_ID, id);
        if (SUCCEEDED(hr)) hr = store->Commit();
        store->Release();
    }
    if (SUCCEEDED(hr)) hr = persist->Save(path.c_str(), TRUE);
    if (persist) persist->Release();
    link->Release();
    return hr;
}

int WINAPI wWinMain(HINSTANCE, HINSTANCE, PWSTR, int) {
    wchar_t path[32768];
    DWORD length = GetModuleFileNameW(nullptr, path, 32768);
    if (!length || length >= 32768) return 1;
    std::wstring exe(path, length);
    auto directory = exe.substr(0, exe.find_last_of(L'\\'));
    const auto nested = directory + L"\\\u6587\u77e9";
    if (!file_exists(directory + L"\\app.py") && file_exists(nested + L"\\app.py")) {
        directory = nested;
        exe = directory + L"\\\u6587\u77e9.exe";
        if (!file_exists(exe)) return 1;
    }
    auto python = directory + L"\\runtime\\pythonw.exe";
    auto script = directory + L"\\app.py";
    if (!file_exists(python) || !file_exists(script)) {
        MessageBoxW(nullptr, L"\u8bf7\u5b8c\u6574\u89e3\u538b\u6587\u77e9\u4fbf\u643a\u5305\uff0c\u5e76\u4fdd\u7559 runtime \u548c\u5e94\u7528\u6587\u4ef6\u3002", Name, MB_ICONERROR);
        return 1;
    }
    const bool persistent = !transient_path(exe);
    SetCurrentProcessExplicitAppUserModelID(AppId);
    SetEnvironmentVariableW(L"WENJU_PRODUCT_ENTRY", persistent ? exe.c_str() : nullptr);
    std::wstring command = quote(python) + L" " + quote(script);
    int argc = 0;
    bool create = false;
    bool skip_shortcuts = false;
    auto argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    for (int i = 1; argv && i < argc; ++i) {
        const std::wstring arg(argv[i]);
        if (arg == L"--shortcuts") create = true;
        else if (arg == L"--no-shortcuts") skip_shortcuts = true;
        else command += L" " + quote(arg);
    }
    if (argv) LocalFree(argv);
    if (command.size() >= 32767) {
        MessageBoxW(nullptr, L"\u542f\u52a8\u53c2\u6570\u8fc7\u957f\u3002", Name, MB_ICONERROR);
        return 1;
    }
    if (persistent && !skip_shortcuts && SUCCEEDED(CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED))) {
        auto desktop = shortcut(CSIDL_DESKTOPDIRECTORY, exe, directory, create);
        auto programs = shortcut(CSIDL_PROGRAMS, exe, directory, create);
        CoUninitialize();
        if (create && (FAILED(desktop) || FAILED(programs)))
            MessageBoxW(nullptr, L"\u90e8\u5206\u5feb\u6377\u65b9\u5f0f\u672a\u80fd\u66f4\u65b0\u3002", Name, MB_ICONWARNING);
    }
    STARTUPINFOW startup = {sizeof(startup)};
    PROCESS_INFORMATION child = {};
    if (!CreateProcessW(python.c_str(), &command[0], nullptr, nullptr, FALSE, CREATE_NO_WINDOW, nullptr,
                        directory.c_str(), &startup, &child)) {
        std::wstring message = L"\u65e0\u6cd5\u542f\u52a8\u6587\u77e9\u3002Win32: " + std::to_wstring(GetLastError());
        MessageBoxW(nullptr, message.c_str(), Name, MB_ICONERROR);
        return 1;
    }
    AllowSetForegroundWindow(child.dwProcessId);
    CloseHandle(child.hThread);
    CloseHandle(child.hProcess);
    return 0;
}
