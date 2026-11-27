// 고객 문의 정리 도구 실행 파일 (Windows)
// 프로그램 파일(HTML/CSS/JS)을 exe 안에 포함해 두었다가, 실행하면
// %LOCALAPPDATA%\CustomerReplyTool 에 풀어 기본 브라우저로 엽니다.
// 인터넷 연결이나 설치가 필요 없습니다.
package main

import (
	"crypto/sha256"
	"embed"
	"encoding/hex"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
)

//go:embed index.html css js docs
var app embed.FS

func main() {
	dir, err := extract()
	if err != nil {
		fail("프로그램 파일을 준비하지 못했습니다.\n\n" + err.Error())
		return
	}
	index := filepath.Join(dir, "index.html")
	if err := exec.Command("rundll32", "url.dll,FileProtocolHandler", index).Start(); err != nil {
		fail("브라우저를 열지 못했습니다.\n아래 파일을 직접 열어 주세요.\n\n" + index)
	}
}

// 포함된 파일 내용으로 버전 폴더를 정해, 새 버전일 때만 다시 풉니다.
func extract() (string, error) {
	var paths []string
	fs.WalkDir(app, ".", func(p string, d fs.DirEntry, err error) error {
		if err == nil && !d.IsDir() {
			paths = append(paths, p)
		}
		return nil
	})
	sort.Strings(paths)
	h := sha256.New()
	for _, p := range paths {
		b, _ := app.ReadFile(p)
		h.Write([]byte(p))
		h.Write(b)
	}
	ver := hex.EncodeToString(h.Sum(nil))[:12]

	base := os.Getenv("LOCALAPPDATA")
	if base == "" {
		base = os.TempDir()
	}
	root := filepath.Join(base, "CustomerReplyTool")
	dir := filepath.Join(root, ver)
	if _, err := os.Stat(filepath.Join(dir, "index.html")); err == nil {
		return dir, nil
	}
	tmp := dir + ".tmp"
	os.RemoveAll(tmp)
	for _, p := range paths {
		b, _ := app.ReadFile(p)
		dst := filepath.Join(tmp, filepath.FromSlash(p))
		if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
			return "", err
		}
		if err := os.WriteFile(dst, b, 0o644); err != nil {
			return "", err
		}
	}
	// 이전 버전 정리
	if old, err := os.ReadDir(root); err == nil {
		for _, e := range old {
			if e.Name() != ver+".tmp" {
				os.RemoveAll(filepath.Join(root, e.Name()))
			}
		}
	}
	if err := os.Rename(tmp, dir); err != nil {
		return "", err
	}
	return dir, nil
}
