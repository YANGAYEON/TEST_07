const E = require('../js/engine.js');
const samples = [
`고객이 로그인이 안 된다고 문의함.
로그 확인해보니 세션 토큰 만료 처리 로직에 버그가 있었음. 해당 로직 수정해서 오늘 오후 3시에 배포 완료함.
고객에게 브라우저 캐시 삭제 후 재로그인하라고 안내 필요`,
`결제가 두 번 됐다고 고객님이 전화함
PG사 결과 조회했고, 중복 승인 1건 확인됨
아마 네트워크 지연으로 재요청된 것 같음
중복건은 승인 취소 처리함. 환불은 3~5영업일 소요 예정
카드사 문자 확인 부탁`,
`엑셀 다운로드 느림 문의
재현 안 됨. 서버 부하 때문일 수도 있음`
];
for (const s of samples) {
  const items = E.analyze(s);
  console.log('----');
  items.forEach(i => console.log(`[${E.LABEL[i.category]}|${i.confidence}${i.uncertain?'|추정':''}] ${i.text}  =>  ${E.polishSentence(i,{plainTerms:true})}`));
  for (const f of ['concise','polite','detailed']) {
    const r = E.buildReply(items, {format:f, apology:true, plainTerms:true, customerName:'홍길동'});
    console.log(`\n== ${f} (missing: ${r.missing})\n` + r.text);
  }
}
