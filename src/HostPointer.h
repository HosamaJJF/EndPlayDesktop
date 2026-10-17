#pragma once

namespace endplaydesktop
{
class Runtime;
bool InstallHostPointerInput(Runtime& runtime);
void UpdateHostPointerLock(bool requested);
void ReleaseHostPointerLock();
bool HostPointerLocked();
} // namespace endplaydesktop
