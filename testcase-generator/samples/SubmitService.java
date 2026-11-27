package com.biz.submit.service;

import java.util.List;
import java.util.Map;

public class SubmitService {

    private SubmitMapper submitMapper;

    /**
     * 제출내역 목록 조회
     */
    public List<Map<String, Object>> selectSubmitList(Map<String, Object> param) {
        String startDt = (String) param.get("startDt");
        String endDt = (String) param.get("endDt");
        if (startDt == null || endDt == null) {
            throw new IllegalArgumentException("조회 기간은 필수입니다.");
        }
        if (startDt.compareTo(endDt) > 0) {
            throw new BizException("시작일은 종료일보다 클 수 없습니다.");
        }
        return submitMapper.selectSubmitList(param);
    }

    public void processRequest(String reqDt, String reqStsCd, int reqAmt) {
        if (reqDt == null) {
            throw new IllegalArgumentException();
        }
        if ("01".equals(reqStsCd)) {
            // 신청 처리
            submitMapper.insertSubmit(reqDt);
        } else if ("02".equals(reqStsCd)) {
            // 취소 처리
            submitMapper.cancelSubmit(reqDt);
        }
        if (reqAmt > 1000000) {
            // 고액 신청 승인 대상
            submitMapper.insertApproval(reqDt);
        }
    }

    public int deleteSubmit(List<String> submitNos) {
        int cnt = 0;
        if (submitNos == null || submitNos.isEmpty()) {
            return 0;
        }
        for (String no : submitNos) {
            try {
                cnt += submitMapper.deleteSubmit(no);
            } catch (DataAccessException e) {
                throw new BizException("삭제 중 오류가 발생했습니다.", e);
            }
        }
        switch (cnt) {
            case 0:
                log.info("삭제 대상 없음");
                break;
            default:
                log.info("삭제 완료");
        }
        return cnt;
    }
}
