/*
 * 업무 도식화 도구 - 내보내기 (모두 브라우저 내부에서 생성, 외부 전송 없음)
 */
(function (global) {
  'use strict';

  function safeName(s) {
    return String(s || 'diagram').replace(/[\\/:*?"<>|\s]+/g, '_').replace(/_+/g, '_').slice(0, 80);
  }

  function download(name, blob) {
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url; a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 2000);
  }

  /** 화면에 그려진 Mermaid SVG를 독립 실행 가능한 SVG 문자열로 변환 */
  function standaloneSvg(svgEl, title) {
    var clone = svgEl.cloneNode(true);
    var vb = (clone.getAttribute('viewBox') || '').split(/[\s,]+/).map(Number);
    var w = vb.length === 4 ? vb[2] : svgEl.getBoundingClientRect().width;
    var h = vb.length === 4 ? vb[3] : svgEl.getBoundingClientRect().height;
    var pad = 24, titleH = title ? 44 : 0;
    var x0 = vb.length === 4 ? vb[0] : 0, y0 = vb.length === 4 ? vb[1] : 0;
    var nw = w + pad * 2, nh = h + pad * 2 + titleH;
    clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    clone.setAttribute('xmlns:xlink', 'http://www.w3.org/1999/xlink');
    clone.setAttribute('viewBox', (x0 - pad) + ' ' + (y0 - pad - titleH) + ' ' + nw + ' ' + nh);
    clone.setAttribute('width', String(Math.ceil(nw)));
    clone.setAttribute('height', String(Math.ceil(nh)));
    clone.removeAttribute('style');
    var ns = 'http://www.w3.org/2000/svg';
    var bg = document.createElementNS(ns, 'rect');
    bg.setAttribute('x', x0 - pad); bg.setAttribute('y', y0 - pad - titleH);
    bg.setAttribute('width', nw); bg.setAttribute('height', nh);
    bg.setAttribute('fill', '#ffffff');
    clone.insertBefore(bg, clone.firstChild);
    if (title) {
      var t = document.createElementNS(ns, 'text');
      t.setAttribute('x', x0); t.setAttribute('y', y0 - pad - titleH + 30);
      t.setAttribute('font-family', 'Malgun Gothic, Apple SD Gothic Neo, Noto Sans KR, sans-serif');
      t.setAttribute('font-size', '20'); t.setAttribute('font-weight', 'bold'); t.setAttribute('fill', '#14213d');
      t.textContent = title;
      bg.parentNode.insertBefore(t, bg.nextSibling);
    }
    var xml = new XMLSerializer().serializeToString(clone);
    return { xml: '<?xml version="1.0" encoding="UTF-8"?>\n' + xml, width: nw, height: nh };
  }

  function saveSvg(svgEl, title, fileBase) {
    var s = standaloneSvg(svgEl, title);
    download(safeName(fileBase) + '.svg', new Blob([s.xml], { type: 'image/svg+xml;charset=utf-8' }));
  }

  function savePng(svgEl, title, fileBase, scale) {
    return new Promise(function (resolve, reject) {
      var s = standaloneSvg(svgEl, title);
      scale = scale || 2;
      var img = new Image();
      img.onload = function () {
        try {
          var c = document.createElement('canvas');
          c.width = Math.ceil(s.width * scale); c.height = Math.ceil(s.height * scale);
          var ctx = c.getContext('2d');
          ctx.fillStyle = '#ffffff'; ctx.fillRect(0, 0, c.width, c.height);
          ctx.drawImage(img, 0, 0, c.width, c.height);
          c.toBlob(function (blob) {
            if (!blob) { reject(new Error('PNG 생성 실패')); return; }
            download(safeName(fileBase) + '.png', blob); resolve();
          }, 'image/png');
        } catch (e) { reject(e); }
      };
      img.onerror = function () { reject(new Error('이미지 변환 실패')); };
      img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(s.xml.replace(/^<\?xml[^>]*>\s*/, ''));
    });
  }

  function saveMmd(code, fileBase) {
    download(safeName(fileBase) + '.mmd', new Blob([code + '\n'], { type: 'text/plain;charset=utf-8' }));
  }

  function saveJson(obj, fileBase) {
    download(safeName(fileBase) + '.json', new Blob([JSON.stringify(obj, null, 2)], { type: 'application/json;charset=utf-8' }));
  }

  function copyText(text) {
    if (navigator.clipboard && global.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise(function (resolve, reject) {
      var ta = document.createElement('textarea');
      ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select();
      try { document.execCommand('copy') ? resolve() : reject(new Error('복사 실패')); } catch (e) { reject(e); }
      ta.remove();
    });
  }

  global.FlowExport = { saveSvg: saveSvg, savePng: savePng, saveMmd: saveMmd, saveJson: saveJson, copyText: copyText, safeName: safeName, standaloneSvg: standaloneSvg };
})(window);
