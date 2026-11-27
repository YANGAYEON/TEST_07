package main

import (
	"syscall"
	"unsafe"
)

// 오류를 Windows 메시지 상자로 표시
func fail(msg string) {
	box := syscall.NewLazyDLL("user32.dll").NewProc("MessageBoxW")
	t, _ := syscall.UTF16PtrFromString(msg)
	c, _ := syscall.UTF16PtrFromString("고객 문의 정리 도구")
	box.Call(0, uintptr(unsafe.Pointer(t)), uintptr(unsafe.Pointer(c)), 0x10)
}
