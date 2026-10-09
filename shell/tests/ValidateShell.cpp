#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <shlobj.h>
#include <shellapi.h>

#include <cstdio>
#include <cstring>
#include <new>
#include <string>
#include <utility>
#include <vector>

// Headless, non-registering validation harness. It calls Initialize and
// QueryContextMenu only; it deliberately never invokes a menu command.
static const CLSID CLSID_TangerineShell = {
    0x7e2c14a9, 0x8d31, 0x4b76, {0xa5, 0xf0, 0x3c, 0x9d, 0x82, 0x16, 0xe4, 0xb2}};
using DllGetClassObjectFn = HRESULT(WINAPI*)(REFCLSID, REFIID, void**);

class DropDataObject final : public IDataObject {
    LONG references_ = 1;
    std::vector<std::wstring> paths_;

public:
    explicit DropDataObject(std::vector<std::wstring> paths) : paths_(std::move(paths)) {}
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid, void** output) override {
        if (!output) return E_POINTER;
        *output = nullptr;
        if (iid != IID_IUnknown && iid != IID_IDataObject) return E_NOINTERFACE;
        *output = static_cast<IDataObject*>(this);
        AddRef();
        return S_OK;
    }
    ULONG STDMETHODCALLTYPE AddRef() override { return static_cast<ULONG>(InterlockedIncrement(&references_)); }
    ULONG STDMETHODCALLTYPE Release() override {
        const ULONG remaining = static_cast<ULONG>(InterlockedDecrement(&references_));
        if (!remaining) delete this;
        return remaining;
    }
    HRESULT STDMETHODCALLTYPE GetData(FORMATETC* format, STGMEDIUM* medium) override {
        if (!format || !medium) return E_POINTER;
        if (format->cfFormat != CF_HDROP || format->dwAspect != DVASPECT_CONTENT ||
            !(format->tymed & TYMED_HGLOBAL)) return DV_E_FORMATETC;
        size_t characterCount = 1;
        for (const auto& path : paths_) characterCount += path.size() + 1;
        const size_t bytes = sizeof(DROPFILES) + characterCount * sizeof(wchar_t);
        HGLOBAL memory = GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, bytes);
        if (!memory) return E_OUTOFMEMORY;
        auto* drop = static_cast<DROPFILES*>(GlobalLock(memory));
        if (!drop) {
            GlobalFree(memory);
            return LastErrorHr();
        }
        drop->pFiles = sizeof(DROPFILES);
        drop->fWide = TRUE;
        auto* destination = reinterpret_cast<wchar_t*>(reinterpret_cast<BYTE*>(drop) + sizeof(DROPFILES));
        for (const auto& path : paths_) {
            memcpy(destination, path.c_str(), (path.size() + 1) * sizeof(wchar_t));
            destination += path.size() + 1;
        }
        *destination = L'\0';
        GlobalUnlock(memory);
        medium->tymed = TYMED_HGLOBAL;
        medium->hGlobal = memory;
        medium->pUnkForRelease = nullptr;
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE GetDataHere(FORMATETC*, STGMEDIUM*) override { return E_NOTIMPL; }
    HRESULT STDMETHODCALLTYPE QueryGetData(FORMATETC* format) override {
        return format && format->cfFormat == CF_HDROP && (format->tymed & TYMED_HGLOBAL)
            ? S_OK : DV_E_FORMATETC;
    }
    HRESULT STDMETHODCALLTYPE GetCanonicalFormatEtc(FORMATETC*, FORMATETC* output) override {
        if (output) output->ptd = nullptr;
        return E_NOTIMPL;
    }
    HRESULT STDMETHODCALLTYPE SetData(FORMATETC*, STGMEDIUM*, BOOL) override { return E_NOTIMPL; }
    HRESULT STDMETHODCALLTYPE EnumFormatEtc(DWORD, IEnumFORMATETC**) override { return E_NOTIMPL; }
    HRESULT STDMETHODCALLTYPE DAdvise(FORMATETC*, DWORD, IAdviseSink*, DWORD*) override { return OLE_E_ADVISENOTSUPPORTED; }
    HRESULT STDMETHODCALLTYPE DUnadvise(DWORD) override { return OLE_E_ADVISENOTSUPPORTED; }
    HRESULT STDMETHODCALLTYPE EnumDAdvise(IEnumSTATDATA**) override { return OLE_E_ADVISENOTSUPPORTED; }

private:
    static HRESULT LastErrorHr() {
        const DWORD error = GetLastError();
        return HRESULT_FROM_WIN32(error ? error : ERROR_GEN_FAILURE);
    }
};

static bool WriteEmptyFile(const std::wstring& path) {
    HANDLE file = CreateFileW(path.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS,
        FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) return false;
    CloseHandle(file);
    return true;
}

static bool ValidateSelection(IClassFactory* factory, const std::vector<std::wstring>& paths,
    bool shouldAppear, const char* label) {
    IDataObject* data = new (std::nothrow) DropDataObject(paths);
    if (!data) return false;
    IShellExtInit* initializer = nullptr;
    HRESULT result = factory->CreateInstance(nullptr, IID_IShellExtInit, reinterpret_cast<void**>(&initializer));
    if (FAILED(result)) {
        data->Release();
        std::fprintf(stderr, "%s: CreateInstance(IShellExtInit) failed: 0x%08lX\n",
            label, static_cast<unsigned long>(result));
        return false;
    }
    result = initializer->Initialize(nullptr, data, nullptr);
    data->Release();
    if (FAILED(result)) {
        initializer->Release();
        std::fprintf(stderr, "%s: Initialize failed: 0x%08lX\n",
            label, static_cast<unsigned long>(result));
        return false;
    }
    IContextMenu* context = nullptr;
    result = initializer->QueryInterface(IID_IContextMenu, reinterpret_cast<void**>(&context));
    initializer->Release();
    if (FAILED(result)) {
        std::fprintf(stderr, "%s: QueryInterface(IContextMenu) failed: 0x%08lX\n",
            label, static_cast<unsigned long>(result));
        return false;
    }
    HMENU menu = CreatePopupMenu();
    if (!menu) {
        context->Release();
        std::fprintf(stderr, "%s: CreatePopupMenu failed\n", label);
        return false;
    }
    result = context->QueryContextMenu(menu, 0, 0x1000, 0x1002, 0);
    context->Release();
    const UINT allocated = HRESULT_CODE(result);
    const int topLevelCount = GetMenuItemCount(menu);
    bool passed = SUCCEEDED(result) && ((allocated == 3 && topLevelCount == 1) == shouldAppear);
    if (shouldAppear && passed) {
        MENUITEMINFOW item{};
        item.cbSize = sizeof(item);
        item.fMask = MIIM_SUBMENU;
        passed = GetMenuItemInfoW(menu, 0, TRUE, &item) && item.hSubMenu && GetMenuItemCount(item.hSubMenu) == 3;
    }
    DestroyMenu(menu);
    std::printf("%s: %s (HRESULT=0x%08lX, allocated=%u, menu_items=%d)\n", label,
        passed ? "PASS" : "FAIL", static_cast<unsigned long>(result), allocated, topLevelCount);
    return passed;
}

int wmain(int argc, wchar_t** argv) {
    if (argc != 2) {
        std::fwprintf(stderr, L"Usage: ValidateShell.exe <path-to-TangerineShell.dll>\n");
        return 2;
    }
    const HRESULT comResult = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    if (FAILED(comResult)) {
        std::fprintf(stderr, "CoInitializeEx failed: 0x%08lX\n", static_cast<unsigned long>(comResult));
        return 2;
    }
    HMODULE module = LoadLibraryW(argv[1]);
    if (!module) {
        const DWORD error = GetLastError();
        CoUninitialize();
        std::fprintf(stderr, "LoadLibraryW failed: %lu\n", static_cast<unsigned long>(error));
        return 2;
    }
    const FARPROC exportedFunction = GetProcAddress(module, "DllGetClassObject");
    DllGetClassObjectFn getClassObject = nullptr;
    static_assert(sizeof(getClassObject) == sizeof(exportedFunction), "Windows function pointers must match");
    std::memcpy(&getClassObject, &exportedFunction, sizeof(getClassObject));
    IClassFactory* factory = nullptr;
    HRESULT result = getClassObject ? getClassObject(CLSID_TangerineShell, IID_IClassFactory,
        reinterpret_cast<void**>(&factory)) : HRESULT_FROM_WIN32(ERROR_PROC_NOT_FOUND);
    if (FAILED(result)) {
        std::fprintf(stderr, "DllGetClassObject failed: 0x%08lX\n", static_cast<unsigned long>(result));
        FreeLibrary(module);
        CoUninitialize();
        return 2;
    }

    wchar_t temporary[MAX_PATH]{};
    const DWORD temporaryLength = GetTempPathW(ARRAYSIZE(temporary), temporary);
    wchar_t directory[MAX_PATH]{};
    swprintf_s(directory, L"%sTangerineShellHarness-%lu", temporary, GetCurrentProcessId());
    bool passed = temporaryLength && temporaryLength < ARRAYSIZE(temporary) &&
        CreateDirectoryW(directory, nullptr);
    std::vector<std::wstring> validFiles, mixedFiles, invalidFiles;
    if (passed) {
        const std::wstring jpg = std::wstring(directory) + L"\\single.jpg";
        const std::wstring png = std::wstring(directory) + L"\\multiple.png";
        const std::wstring text = std::wstring(directory) + L"\\filtered.txt";
        passed = WriteEmptyFile(jpg) && WriteEmptyFile(png) && WriteEmptyFile(text);
        validFiles = {jpg};
        mixedFiles = {jpg, png};
        invalidFiles = {jpg, text};
        if (passed) {
            passed = ValidateSelection(factory, validFiles, true, "single supported image") &&
                ValidateSelection(factory, mixedFiles, true, "multiple supported images") &&
                ValidateSelection(factory, invalidFiles, false, "mixed image and unsupported file") &&
                ValidateSelection(factory, {text}, false, "single unsupported file");
        }
        DeleteFileW(jpg.c_str());
        DeleteFileW(png.c_str());
        DeleteFileW(text.c_str());
        RemoveDirectoryW(directory);
    }
    if (!passed) std::fprintf(stderr, "Harness setup or validation failed.\n");
    factory->Release();
    FreeLibrary(module);
    CoUninitialize();
    return passed ? 0 : 1;
}
