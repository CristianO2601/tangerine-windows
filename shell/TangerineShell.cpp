#define UNICODE
#define _UNICODE
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shlobj.h>
#include <shellapi.h>
#include <strsafe.h>

#include <algorithm>
#include <cstdio>
#include <cwchar>
#include <new>
#include <string>
#include <vector>

// Fixed CLSID for Tangerine's in-process Explorer context-menu handler.
// {7E2C14A9-8D31-4B76-A5F0-3C9D8216E4B2}
static const CLSID CLSID_TangerineShell = {
    0x7e2c14a9, 0x8d31, 0x4b76, {0xa5, 0xf0, 0x3c, 0x9d, 0x82, 0x16, 0xe4, 0xb2}};
static constexpr wchar_t kRegistryKey[] = L"Software\\Tangerine\\ShellIntegration";
static constexpr char kVerbsA[][32] = {"Tangerine.Pdf.Name", "Tangerine.Pdf.Received", "Tangerine.Pdf.Configure"};
static constexpr wchar_t kVerbsW[][32] = {L"Tangerine.Pdf.Name", L"Tangerine.Pdf.Received", L"Tangerine.Pdf.Configure"};

static HMODULE g_module = nullptr;
static volatile LONG g_objects = 0;
static volatile LONG g_locks = 0;
static constexpr size_t kMaxSelectionCount = 10000;
static constexpr size_t kMaxManifestBytes = 8 * 1024 * 1024 - 1024;

static HRESULT LastErrorHr() noexcept {
    const DWORD error = GetLastError();
    return HRESULT_FROM_WIN32(error ? error : ERROR_GEN_FAILURE);
}

static std::wstring EnvironmentPath(const wchar_t* name) {
    const DWORD required = GetEnvironmentVariableW(name, nullptr, 0);
    if (!required) throw LastErrorHr();
    std::vector<wchar_t> buffer(required, L'\0');
    const DWORD written = GetEnvironmentVariableW(name, buffer.data(), required);
    if (!written || written >= required) throw HRESULT_FROM_WIN32(ERROR_BAD_ENVIRONMENT);
    return std::wstring(buffer.data(), written);
}

static void EnsureDirectory(const std::wstring& path) {
    if (!CreateDirectoryW(path.c_str(), nullptr) && GetLastError() != ERROR_ALREADY_EXISTS)
        throw LastErrorHr();
    const DWORD attributes = GetFileAttributesW(path.c_str());
    if (attributes == INVALID_FILE_ATTRIBUTES || !(attributes & FILE_ATTRIBUTE_DIRECTORY))
        throw HRESULT_FROM_WIN32(ERROR_DIRECTORY);
}

static std::string ProcessBaseNameUtf8() {
    std::vector<wchar_t> path(32768, L'\0');
    const DWORD length = GetModuleFileNameW(nullptr, path.data(), static_cast<DWORD>(path.size()));
    if (!length || length >= path.size()) return "unavailable";
    const wchar_t* base = path.data();
    for (const wchar_t* cursor = path.data(); *cursor; ++cursor) {
        if (*cursor == L'\\' || *cursor == L'/') base = cursor + 1;
    }
    const int utf8Length = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, base, -1,
        nullptr, 0, nullptr, nullptr);
    if (utf8Length <= 1) return "unavailable";
    std::string name(static_cast<size_t>(utf8Length), '\0');
    if (!WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, base, -1,
            name.data(), utf8Length, nullptr, nullptr))
        return "unavailable";
    name.pop_back();
    for (char& character : name) {
        const unsigned char byte = static_cast<unsigned char>(character);
        if (byte < 0x20 || byte == 0x7f) character = '_';
    }
    return name;
}

static std::wstring AppDataDirectory() {
    return EnvironmentPath(L"APPDATA") + L"\\Tangerine";
}

// DiagnosticLogging is an opt-in REG_DWORD. Logs contain no selected paths,
// executable path, or manifest path, and never grow beyond one MiB.
static void LogEvent(const char* event, UINT count = 0, HRESULT result = S_OK) noexcept {
    try {
        DWORD enabled = 0;
        DWORD bytes = sizeof(enabled);
        if (RegGetValueW(HKEY_CURRENT_USER, kRegistryKey, L"DiagnosticLogging",
                RRF_RT_REG_DWORD, nullptr, &enabled, &bytes) != ERROR_SUCCESS || !enabled)
            return;

        const std::wstring directory = AppDataDirectory();
        EnsureDirectory(directory);
        const std::wstring path = directory + L"\\shell.log";
        HANDLE file = CreateFileW(path.c_str(), FILE_APPEND_DATA | FILE_READ_ATTRIBUTES,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr, OPEN_ALWAYS,
            FILE_ATTRIBUTE_NORMAL, nullptr);
        if (file == INVALID_HANDLE_VALUE) return;

        LARGE_INTEGER size{};
        if (GetFileSizeEx(file, &size) && size.QuadPart < 1024 * 1024) {
            SYSTEMTIME now{};
            GetSystemTime(&now);
            char line[256]{};
            const int length = snprintf(line, sizeof(line),
                "%04u-%02u-%02uT%02u:%02u:%02uZ host=%s hostpid=%lu event=%s count=%u hr=0x%08lX\r\n",
                now.wYear, now.wMonth, now.wDay, now.wHour, now.wMinute, now.wSecond,
                ProcessBaseNameUtf8().c_str(), GetCurrentProcessId(), event, count,
                static_cast<unsigned long>(result));
            if (length > 0 && length < static_cast<int>(sizeof(line)) &&
                size.QuadPart + length <= 1024 * 1024) {
                DWORD written = 0;
                WriteFile(file, line, static_cast<DWORD>(length), &written, nullptr);
            }
        }
        CloseHandle(file);
    } catch (...) {
        // Diagnostics must never interfere with Explorer.
    }
}

static bool IsSupportedImage(const std::wstring& path) {
    const size_t dot = path.find_last_of(L'.');
    if (dot == std::wstring::npos) return false;
    static constexpr const wchar_t* extensions[] = {
        L".jpg", L".jpeg", L".jpe", L".jfif", L".png", L".bmp", L".dib",
        L".gif", L".tif", L".tiff", L".webp", L".ico", L".heic", L".heif",
        L".avif", L".svg"};
    bool found = false;
    for (const wchar_t* extension : extensions) {
        if (_wcsicmp(path.c_str() + dot, extension) == 0) {
            found = true;
            break;
        }
    }
    if (!found) return false;
    const DWORD attributes = GetFileAttributesW(path.c_str());
    return attributes != INVALID_FILE_ATTRIBUTES && !(attributes & FILE_ATTRIBUTE_DIRECTORY);
}

static std::wstring ReadExecutablePath() {
    DWORD bytes = 0;
    LONG status = RegGetValueW(HKEY_CURRENT_USER, kRegistryKey, L"ExecutablePath",
        RRF_RT_REG_SZ, nullptr, nullptr, &bytes);
    if (status != ERROR_SUCCESS) throw HRESULT_FROM_WIN32(status);
    if (bytes < sizeof(wchar_t) || bytes > 32768 * sizeof(wchar_t))
        throw HRESULT_FROM_WIN32(ERROR_INVALID_DATA);
    std::vector<wchar_t> buffer(bytes / sizeof(wchar_t) + 1, L'\0');
    status = RegGetValueW(HKEY_CURRENT_USER, kRegistryKey, L"ExecutablePath",
        RRF_RT_REG_SZ, nullptr, buffer.data(), &bytes);
    if (status != ERROR_SUCCESS) throw HRESULT_FROM_WIN32(status);
    std::wstring result(buffer.data());
    if (result.empty() || GetFileAttributesW(result.c_str()) == INVALID_FILE_ATTRIBUTES)
        throw HRESULT_FROM_WIN32(ERROR_FILE_NOT_FOUND);
    return result;
}

static std::wstring QuoteArgument(const std::wstring& value) {
    std::wstring quoted(1, L'"');
    size_t slashes = 0;
    for (const wchar_t character : value) {
        if (character == L'\\') {
            ++slashes;
            continue;
        }
        quoted.append(character == L'"' ? slashes * 2 + 1 : slashes, L'\\');
        quoted += character;
        slashes = 0;
    }
    quoted.append(slashes * 2, L'\\');
    quoted += L'"';
    return quoted;
}

static std::string JsonString(const std::wstring& value) {
    const int sourceLength = static_cast<int>(value.size());
    const int length = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, value.data(), sourceLength,
        nullptr, 0, nullptr, nullptr);
    if (length <= 0 && sourceLength != 0) throw LastErrorHr();
    std::string utf8(static_cast<size_t>(length), '\0');
    if (length && !WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, value.data(), sourceLength,
            utf8.data(), length, nullptr, nullptr))
        throw LastErrorHr();

    std::string escaped(1, '"');
    static constexpr char hex[] = "0123456789abcdef";
    for (const unsigned char byte : utf8) {
        if (byte == '"' || byte == '\\') {
            escaped += '\\';
            escaped += static_cast<char>(byte);
        } else if (byte < 0x20) {
            escaped += "\\u00";
            escaped += hex[byte >> 4];
            escaped += hex[byte & 0x0f];
        } else {
            escaped += static_cast<char>(byte);
        }
    }
    escaped += '"';
    return escaped;
}

static HRESULT WriteManifest(const std::vector<std::wstring>& paths, std::wstring& manifest) {
    std::wstring directory;
    HANDLE file = INVALID_HANDLE_VALUE;
    try {
        if (paths.size() > kMaxSelectionCount)
            throw HRESULT_FROM_WIN32(ERROR_TOO_MANY_NAMES);

        // Bound serialized output before allocating the request file. Keep a
        // one-KiB margin below the consumer's eight-MiB input limit.
        std::string json = "[";
        for (size_t index = 0; index < paths.size(); ++index) {
            const std::string encoded = JsonString(paths[index]);
            const size_t separatorLength = index ? 1 : 0;
            if (json.size() > kMaxManifestBytes - separatorLength ||
                encoded.size() > kMaxManifestBytes - json.size() - separatorLength)
                throw HRESULT_FROM_WIN32(ERROR_FILE_TOO_LARGE);
            if (separatorLength) json += ',';
            json += encoded;
        }
        if (json.size() >= kMaxManifestBytes)
            throw HRESULT_FROM_WIN32(ERROR_FILE_TOO_LARGE);
        json += ']';

        directory = AppDataDirectory();
        EnsureDirectory(directory);
        directory += L"\\request-queue";
        EnsureDirectory(directory);

        GUID id{};
        HRESULT result = CoCreateGuid(&id);
        if (FAILED(result)) throw result;
        wchar_t guid[40]{};
        if (!StringFromGUID2(id, guid, ARRAYSIZE(guid))) throw E_UNEXPECTED;
        manifest = directory + L"\\selection-" + guid + L".json";

        file = CreateFileW(manifest.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_NEW,
            FILE_ATTRIBUTE_NORMAL, nullptr);
        if (file == INVALID_HANDLE_VALUE) throw LastErrorHr();
        size_t offset = 0;
        while (offset < json.size()) {
            const DWORD chunk = static_cast<DWORD>((std::min)(json.size() - offset, size_t(1024 * 1024)));
            DWORD written = 0;
            if (!WriteFile(file, json.data() + offset, chunk, &written, nullptr)) throw LastErrorHr();
            if (!written) throw HRESULT_FROM_WIN32(ERROR_WRITE_FAULT);
            offset += written;
        }
        if (!FlushFileBuffers(file)) throw LastErrorHr();
        CloseHandle(file);
        file = INVALID_HANDLE_VALUE;
        return S_OK;
    } catch (HRESULT error) {
        if (file != INVALID_HANDLE_VALUE) CloseHandle(file);
        if (!manifest.empty()) DeleteFileW(manifest.c_str());
        return error;
    } catch (...) {
        if (file != INVALID_HANDLE_VALUE) CloseHandle(file);
        if (!manifest.empty()) DeleteFileW(manifest.c_str());
        return E_OUTOFMEMORY;
    }
}

// action 0/1 are quick menu paths. Configure opens the app's interactive flow.
static HRESULT LaunchTangerine(const std::vector<std::wstring>& paths, UINT action) {
    std::wstring manifest;
    HRESULT result = WriteManifest(paths, manifest);
    if (FAILED(result)) {
        LogEvent("ManifestFailed", static_cast<UINT>(paths.size()), result);
        return result;
    }
    try {
        const std::wstring executable = ReadExecutablePath();
        std::wstring command = QuoteArgument(executable) + L" --images-to-pdf --selection-manifest " +
            QuoteArgument(manifest) + L" --pdf-order " + (action == 0 ? L"name" : L"received");
        if (action < 2) command += L" --pdf-quick";

        STARTUPINFOW startup{};
        startup.cb = sizeof(startup);
        PROCESS_INFORMATION process{};
        if (!CreateProcessW(executable.c_str(), command.data(), nullptr, nullptr, FALSE,
                CREATE_UNICODE_ENVIRONMENT, nullptr, nullptr, &startup, &process))
            throw LastErrorHr();
        CloseHandle(process.hThread);
        CloseHandle(process.hProcess);
        LogEvent("Launch", static_cast<UINT>(paths.size()));
        return S_OK;
    } catch (HRESULT error) {
        DeleteFileW(manifest.c_str());
        LogEvent("LaunchFailed", static_cast<UINT>(paths.size()), error);
        return error;
    } catch (...) {
        DeleteFileW(manifest.c_str());
        LogEvent("LaunchFailed", static_cast<UINT>(paths.size()), E_OUTOFMEMORY);
        return E_OUTOFMEMORY;
    }
}

class TangerineContextMenu final : public IShellExtInit, public IContextMenu {
    volatile LONG references_ = 1;
    std::vector<std::wstring> paths_;

public:
    TangerineContextMenu() { InterlockedIncrement(&g_objects); }
    ~TangerineContextMenu() { InterlockedDecrement(&g_objects); }

    IFACEMETHODIMP QueryInterface(REFIID iid, void** output) override {
        if (!output) return E_POINTER;
        *output = nullptr;
        if (iid == IID_IUnknown || iid == IID_IShellExtInit)
            *output = static_cast<IShellExtInit*>(this);
        else if (iid == IID_IContextMenu)
            *output = static_cast<IContextMenu*>(this);
        else
            return E_NOINTERFACE;
        AddRef();
        return S_OK;
    }
    IFACEMETHODIMP_(ULONG) AddRef() override { return static_cast<ULONG>(InterlockedIncrement(&references_)); }
    IFACEMETHODIMP_(ULONG) Release() override {
        const ULONG remaining = static_cast<ULONG>(InterlockedDecrement(&references_));
        if (!remaining) delete this;
        return remaining;
    }

    IFACEMETHODIMP Initialize(PCIDLIST_ABSOLUTE, IDataObject* data, HKEY) override {
        paths_.clear();
        if (!data) return E_INVALIDARG;
        FORMATETC format{CF_HDROP, nullptr, DVASPECT_CONTENT, -1, TYMED_HGLOBAL};
        STGMEDIUM medium{};
        HRESULT result = data->GetData(&format, &medium);
        if (FAILED(result)) {
            LogEvent("InitializeNoDrop", 0, result);
            return result;
        }
        try {
            if (medium.tymed != TYMED_HGLOBAL || !medium.hGlobal) throw DV_E_TYMED;
            const HDROP drop = static_cast<HDROP>(medium.hGlobal);
            const UINT count = DragQueryFileW(drop, 0xffffffff, nullptr, 0);
            bool valid = count > 0;
            for (UINT index = 0; valid && index < count; ++index) {
                const UINT length = DragQueryFileW(drop, index, nullptr, 0);
                if (!length) {
                    valid = false;
                    break;
                }
                std::vector<wchar_t> buffer(length + 1, L'\0');
                if (DragQueryFileW(drop, index, buffer.data(), length + 1) != length ||
                    !IsSupportedImage(buffer.data())) {
                    valid = false;
                    break;
                }
                paths_.emplace_back(buffer.data(), length);
            }
            if (!valid) paths_.clear();
            ReleaseStgMedium(&medium);
            LogEvent(valid ? "InitializeImages" : "InitializeFiltered", count);
            return S_OK;
        } catch (HRESULT error) {
            ReleaseStgMedium(&medium);
            paths_.clear();
            return error;
        } catch (...) {
            ReleaseStgMedium(&medium);
            paths_.clear();
            return E_OUTOFMEMORY;
        }
    }

    IFACEMETHODIMP QueryContextMenu(HMENU menu, UINT index, UINT first, UINT last, UINT flags) override {
        if (paths_.empty() || (flags & CMF_DEFAULTONLY) || last < first || last - first < 2) {
            LogEvent("QuerySkipped", static_cast<UINT>(paths_.size()));
            return MAKE_HRESULT(SEVERITY_SUCCESS, 0, 0);
        }
        HMENU submenu = CreatePopupMenu();
        if (!submenu) return LastErrorHr();
        static constexpr const wchar_t* labels[] = {
            L"Por nombre de archivo (A-Z natural)", L"Orden recibido", L"Configurar y reordenar..."};
        for (UINT itemIndex = 0; itemIndex < ARRAYSIZE(labels); ++itemIndex) {
            MENUITEMINFOW item{};
            item.cbSize = sizeof(item);
            item.fMask = MIIM_ID | MIIM_STRING;
            item.wID = first + itemIndex;
            item.dwTypeData = const_cast<wchar_t*>(labels[itemIndex]);
            if (!InsertMenuItemW(submenu, itemIndex, TRUE, &item)) {
                const HRESULT error = LastErrorHr();
                DestroyMenu(submenu);
                return error;
            }
        }
        MENUITEMINFOW parent{};
        parent.cbSize = sizeof(parent);
        parent.fMask = MIIM_STRING | MIIM_SUBMENU;
        parent.dwTypeData = const_cast<wchar_t*>(L"Tangerine — PDF");
        parent.hSubMenu = submenu;
        if (!InsertMenuItemW(menu, index, TRUE, &parent)) {
            const HRESULT error = LastErrorHr();
            DestroyMenu(submenu);
            return error;
        }
        LogEvent("QueryInserted", static_cast<UINT>(paths_.size()));
        return MAKE_HRESULT(SEVERITY_SUCCESS, 0, 3);
    }

    IFACEMETHODIMP InvokeCommand(CMINVOKECOMMANDINFO* info) override {
        if (!info || info->cbSize < sizeof(CMINVOKECOMMANDINFO)) return E_INVALIDARG;
        UINT action = 3;
        const auto* extended = reinterpret_cast<const CMINVOKECOMMANDINFOEX*>(info);
        if (info->cbSize >= sizeof(CMINVOKECOMMANDINFOEX) &&
            (info->fMask & CMIC_MASK_UNICODE) && HIWORD(extended->lpVerbW)) {
            for (UINT index = 0; index < ARRAYSIZE(kVerbsW); ++index)
                if (_wcsicmp(extended->lpVerbW, kVerbsW[index]) == 0) action = index;
        } else if (HIWORD(info->lpVerb)) {
            for (UINT index = 0; index < ARRAYSIZE(kVerbsA); ++index)
                if (_stricmp(info->lpVerb, kVerbsA[index]) == 0) action = index;
        } else {
            action = LOWORD(info->lpVerb);
        }
        if (action >= ARRAYSIZE(kVerbsW) || paths_.empty()) return E_INVALIDARG;
        return LaunchTangerine(paths_, action);
    }

    IFACEMETHODIMP GetCommandString(UINT_PTR id, UINT flags, UINT*, LPSTR buffer, UINT capacity) override {
        if (id >= ARRAYSIZE(kVerbsW)) return E_INVALIDARG;
        if (flags == GCS_VALIDATEA || flags == GCS_VALIDATEW) return S_OK;
        if (!buffer || !capacity) return E_POINTER;
        if (flags == GCS_VERBA) return StringCchCopyA(buffer, capacity, kVerbsA[id]);
        if (flags == GCS_VERBW) return StringCchCopyW(reinterpret_cast<LPWSTR>(buffer), capacity, kVerbsW[id]);
        if (flags == GCS_HELPTEXTW)
            return StringCchCopyW(reinterpret_cast<LPWSTR>(buffer), capacity,
                L"Crea un PDF con las imágenes seleccionadas.");
        if (flags == GCS_HELPTEXTA)
            return StringCchCopyA(buffer, capacity, "Create a PDF from the selected images.");
        return E_NOTIMPL;
    }
};

class TangerineClassFactory final : public IClassFactory {
    volatile LONG references_ = 1;

public:
    TangerineClassFactory() { InterlockedIncrement(&g_objects); }
    ~TangerineClassFactory() { InterlockedDecrement(&g_objects); }
    IFACEMETHODIMP QueryInterface(REFIID iid, void** output) override {
        if (!output) return E_POINTER;
        *output = nullptr;
        if (iid != IID_IUnknown && iid != IID_IClassFactory) return E_NOINTERFACE;
        *output = static_cast<IClassFactory*>(this);
        AddRef();
        return S_OK;
    }
    IFACEMETHODIMP_(ULONG) AddRef() override { return static_cast<ULONG>(InterlockedIncrement(&references_)); }
    IFACEMETHODIMP_(ULONG) Release() override {
        const ULONG remaining = static_cast<ULONG>(InterlockedDecrement(&references_));
        if (!remaining) delete this;
        return remaining;
    }
    IFACEMETHODIMP CreateInstance(IUnknown* outer, REFIID iid, void** output) override {
        if (!output) return E_POINTER;
        *output = nullptr;
        if (outer) return CLASS_E_NOAGGREGATION;
        auto* object = new (std::nothrow) TangerineContextMenu();
        if (!object) return E_OUTOFMEMORY;
        const HRESULT result = object->QueryInterface(iid, output);
        object->Release();
        return result;
    }
    IFACEMETHODIMP LockServer(BOOL lock) override {
        if (lock) InterlockedIncrement(&g_locks);
        else if (InterlockedDecrement(&g_locks) < 0) {
            InterlockedIncrement(&g_locks);
            return E_UNEXPECTED;
        }
        return S_OK;
    }
};

extern "C" HRESULT __stdcall DllGetClassObject(REFCLSID clsid, REFIID iid, void** output) {
    if (!output) return E_POINTER;
    *output = nullptr;
    if (clsid != CLSID_TangerineShell) return CLASS_E_CLASSNOTAVAILABLE;
    auto* factory = new (std::nothrow) TangerineClassFactory();
    if (!factory) return E_OUTOFMEMORY;
    const HRESULT result = factory->QueryInterface(iid, output);
    factory->Release();
    return result;
}

extern "C" HRESULT __stdcall DllCanUnloadNow() {
    return InterlockedCompareExchange(&g_objects, 0, 0) == 0 &&
        InterlockedCompareExchange(&g_locks, 0, 0) == 0 ? S_OK : S_FALSE;
}

BOOL WINAPI DllMain(HINSTANCE module, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        g_module = module;
        DisableThreadLibraryCalls(module);
    }
    return TRUE;
}
