#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>
#include "detours.h"

static decltype(&CreateProcessW) real_create = CreateProcessW;
static decltype(&CreateProcessAsUserW) real_create_user = CreateProcessAsUserW;
static wchar_t target_path[32768];

static bool helper_launch(LPCWSTR application, LPCWSTR command, DWORD flags) {
    if (flags & (DEBUG_PROCESS | DEBUG_ONLY_THIS_PROCESS)) return false;
    int argc = 0;
    LPWSTR *argv = CommandLineToArgvW(command ? command : L"", &argc);
    if (!argv) return false;
    LPCWSTR image = application ? application : (argc ? argv[0] : L"");
    bool match = !_wcsicmp(image, target_path);
    bool helper = false;
    unsigned types = 0;
    for (int i = 1; match && i < argc; ++i) {
        if (!wcscmp(argv[i], L"--")) break;
        if (!wcsncmp(argv[i], L"--type=", 7)) ++types;
        if (!_wcsicmp(argv[i], L"--type=renderer") ||
            !_wcsicmp(argv[i], L"--type=gpu-process") ||
            !_wcsicmp(argv[i], L"--type=utility") ||
            !_wcsicmp(argv[i], L"--type=crashpad-handler")) helper = true;
    }
    LocalFree(argv);
    // Duplicate type arguments must not turn an ordinary main/relaunch into an
    // unchecked helper. Chromium helpers always use exactly one --type value.
    return match && helper && types == 1;
}

static BOOL finish_child(BOOL ok, DWORD flags, LPPROCESS_INFORMATION pi) {
    if (!ok) return FALSE;
    if (DebugActiveProcessStop(pi->dwProcessId) &&
        ((flags & CREATE_SUSPENDED) || ResumeThread(pi->hThread) != (DWORD)-1)) return TRUE;
    DWORD error = GetLastError();
    TerminateProcess(pi->hProcess, ERROR_PROCESS_ABORTED);
    CloseHandle(pi->hProcess);
    CloseHandle(pi->hThread);
    ZeroMemory(pi, sizeof(*pi));
    SetLastError(error);
    return FALSE;
}

static BOOL WINAPI create_hook(LPCWSTR app, LPWSTR cmd, LPSECURITY_ATTRIBUTES pa,
    LPSECURITY_ATTRIBUTES ta, BOOL inherit, DWORD flags, LPVOID env, LPCWSTR cwd,
    LPSTARTUPINFOW si, LPPROCESS_INFORMATION pi) {
    if (!helper_launch(app, cmd, flags)) return real_create(app, cmd, pa, ta, inherit, flags, env, cwd, si, pi);
    BOOL ok = real_create(app, cmd, pa, ta, inherit, flags | DEBUG_ONLY_THIS_PROCESS | CREATE_SUSPENDED, env, cwd, si, pi);
    return finish_child(ok, flags, pi);
}

static BOOL WINAPI create_user_hook(HANDLE token, LPCWSTR app, LPWSTR cmd, LPSECURITY_ATTRIBUTES pa,
    LPSECURITY_ATTRIBUTES ta, BOOL inherit, DWORD flags, LPVOID env, LPCWSTR cwd,
    LPSTARTUPINFOW si, LPPROCESS_INFORMATION pi) {
    if (!helper_launch(app, cmd, flags)) return real_create_user(token, app, cmd, pa, ta, inherit, flags, env, cwd, si, pi);
    BOOL ok = real_create_user(token, app, cmd, pa, ta, inherit, flags | DEBUG_ONLY_THIS_PROCESS | CREATE_SUSPENDED, env, cwd, si, pi);
    return finish_child(ok, flags, pi);
}

extern "C" __declspec(dllexport) void WINAPI Anchor() {}
extern "C" __declspec(dllexport) BOOL WINAPI Inject(HANDLE process, LPCSTR path) {
    return DetourUpdateProcessWithDll(process, &path, 1);
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID) {
    if (reason != DLL_PROCESS_ATTACH) return TRUE;
    DisableThreadLibraryCalls(instance);
    wchar_t image[32768];
    if (!GetModuleFileNameW(NULL, image, 32768)) return FALSE;
    if (!GetEnvironmentVariableW(L"CLAUDEC_TAKEOVER_TARGET", target_path, 32768) || _wcsicmp(image, target_path)) return TRUE;
    DetourRestoreAfterWith();
    if (DetourTransactionBegin() != NO_ERROR || DetourUpdateThread(GetCurrentThread()) != NO_ERROR ||
        DetourAttach(&(PVOID&)real_create, create_hook) != NO_ERROR ||
        DetourAttach(&(PVOID&)real_create_user, create_user_hook) != NO_ERROR ||
        DetourTransactionCommit() != NO_ERROR) return FALSE;
    return TRUE;
}
