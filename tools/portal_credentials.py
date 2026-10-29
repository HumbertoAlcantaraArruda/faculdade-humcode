"""Credencial FTPS no cofre do Windows; nunca grava a senha no projeto."""
import ctypes
from ctypes import wintypes
import getpass
import os
import sys

import deploy

TARGET = 'Humcode/FTPS/' + deploy.FTP_HOST + '/' + deploy.FTP_USER


class Credential(ctypes.Structure):
    _fields_ = [('Flags',wintypes.DWORD),('Type',wintypes.DWORD),('TargetName',wintypes.LPWSTR),('Comment',wintypes.LPWSTR),('LastWritten',wintypes.FILETIME),('CredentialBlobSize',wintypes.DWORD),('CredentialBlob',ctypes.POINTER(ctypes.c_ubyte)),('Persist',wintypes.DWORD),('AttributeCount',wintypes.DWORD),('Attributes',ctypes.c_void_p),('TargetAlias',wintypes.LPWSTR),('UserName',wintypes.LPWSTR)]


def api():
    if os.name != 'nt':
        raise RuntimeError('O cofre de credenciais requer Windows.')
    lib = ctypes.WinDLL('advapi32',use_last_error=True)
    lib.CredWriteW.argtypes = [ctypes.POINTER(Credential),wintypes.DWORD]
    lib.CredWriteW.restype = wintypes.BOOL
    lib.CredReadW.argtypes = [wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.POINTER(ctypes.POINTER(Credential))]
    lib.CredReadW.restype = wintypes.BOOL
    lib.CredFree.argtypes = [ctypes.c_void_p]
    return lib


def save(password, target=TARGET, user=deploy.FTP_USER):
    blob = password.encode('utf-16-le')
    buffer = (ctypes.c_ubyte*len(blob)).from_buffer_copy(blob)
    record = Credential(Type=1,TargetName=target,CredentialBlobSize=len(blob),CredentialBlob=buffer,Persist=2,UserName=user)
    if not api().CredWriteW(ctypes.byref(record),0):
        raise ctypes.WinError(ctypes.get_last_error())


def read(target=TARGET):
    lib = api()
    pointer = ctypes.POINTER(Credential)()
    if not lib.CredReadW(target,1,0,ctypes.byref(pointer)):
        raise RuntimeError('Cadastre a senha no cofre do Windows com --store (alvo ' + target + ').')
    try:
        record = pointer.contents
        return ctypes.string_at(record.CredentialBlob,record.CredentialBlobSize).decode('utf-16-le')
    finally:
        lib.CredFree(pointer)


if __name__ == '__main__':
    if sys.argv[1:] == ['--store']:
        save(getpass.getpass('Senha FTPS (cofre Windows): '))
        print('Credencial FTPS guardada no cofre do Windows.')
    else:
        import update_portal
        update_portal.getpass.getpass = lambda prompt: read()
        update_portal.main()
