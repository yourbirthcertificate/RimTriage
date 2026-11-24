@echo off
if exist "%~dp0RimWorldModApplier.exe" (
  start "" "%~dp0RimWorldModApplier.exe"
) else (
  start "" pyw "%~dp0rimworld_mod_applier.py"
)
