"""Hailo 장치 공유 — 여러 모델을 하나의 VDevice 에 올린다.

왜 필요한가:
    **`VDevice()` 는 물리 장치당 하나만 만들 수 있다.** 두 번째 생성은
    `HAILO_OUT_OF_PHYSICAL_DEVICES`(error 74)로 실패한다(실측 확인).
    버튼 검출(console_v2)과 손 검출(팜+핸드)을 함께 쓰려면 장치를 공유해야 한다.

    물리 NPU 가 기기당 하나이므로 **모듈 수준 싱글턴이 하드웨어 구조를 그대로 반영**한다.
    억지 전역 상태가 아니다. 덕분에 `create_detector()` 시그니처를 바꾸지 않아도 되고,
    호출부 5곳(camera_thread·bench_detector·tune_exposure·score_hef·replay_raw)이
    그대로 동작한다.

⚠️ **스케줄러를 쓰면 `network_group.activate()` 를 직접 호출하지 않는다.**
   ROUND_ROBIN 스케줄러가 컨텍스트 전환을 관리하므로, 수동 활성화는 오히려 장치를
   독점해 다른 모델을 막는다. (2026-07-21 프로브에서 3모델 동시 구동 확인)

   🔴 **미해결 — 외부 blaze 소스가 아직 `activate()` 를 부른다 (2026-08-03 확인)**
   기동 때마다 이 경고가 뜬다:
       WARNING:pyhailort:Calls to `activate()` when working with scheduler are
       deprecated! On future versions this call will raise an error.
   호출처는 우리 코드가 아니라 손 검출용 blaze 소스 3곳이다:
       ~/hoi_probe/blaze_app_python/blaze_hailo/hailo_inference.py:134, 156
       ~/hoi_probe/blaze_app_python/blaze_hailo/blazedetector.py:199
       ~/hoi_probe/blaze_app_python/blaze_hailo/blazelandmark.py:126
   **지금은 무해하다** — 세 모델이 정상 동작한다(위 프로브·현행 기동 로그).
   문제가 되는 시점 = **HailoRT 를 5.x 로 올릴 때**. 그때는 `.hef` 재변환
   (현행 .hef 는 DFC 3.33.1 산출물이라 4.x 전용)과 **묶어서** 이 3곳도 고쳐야 한다.
   ⚠️ 그 소스는 repo 밖에 있어 클론·sop-pi-2 에서는 손 검출이 자동 비활성된다
      (vendoring 미결) — 두 문제를 같이 처리하는 편이 낫다.

성능 영향 (2026-07-21 A/B 실측):
    console_v2 단독 8.15ms vs 팜+핸드 동시 로드 8.14ms — **평균 저하 없음**.
    p95 만 9.24 → 11.33ms 로 소폭 증가하나 프레임 간격(약 80ms) 대비 여유 5배.

설계 문서: `docs/superpowers/specs/2026-07-22-detector-vdevice-공유-design.md`
"""

import os
import threading

# ⚠️ RLock 이어야 한다 — configure() 가 락을 잡은 채 get_vdevice() 를 부르고,
#    그 안에서 같은 락을 다시 잡는다. 일반 Lock 이면 자기 자신을 기다리며 교착한다
#    (2026-07-22 실측: create_detector() 가 응답 없이 멈춤).
_lock = threading.RLock()
_vdevice = None
_groups = {}          # {hef 절대경로: network_group} — 같은 모델을 두 번 올리지 않는다


def get_vdevice():
    """공유 VDevice 를 반환한다(최초 1회 생성).

    카메라 스레드와 GUI 스레드가 동시에 부를 수 있어 락으로 보호한다.
    """
    global _vdevice
    if _vdevice is None:
        with _lock:
            if _vdevice is None:                 # 락 안에서 재확인 (double-checked)
                from hailo_platform import HailoSchedulingAlgorithm, VDevice
                params = VDevice.create_params()
                params.scheduling_algorithm = HailoSchedulingAlgorithm.ROUND_ROBIN
                _vdevice = VDevice(params)
    return _vdevice


def configure(hef_path):
    """HEF 를 공유 장치에 올리고 network_group 을 반환한다.

    같은 경로를 다시 부르면 이미 올린 것을 준다 — 중복 configure 는 자원만 먹는다.
    """
    path = os.path.abspath(hef_path)
    if not os.path.exists(path):
        raise FileNotFoundError(f"HEF 모델이 없습니다: {path}")
    ng = _groups.get(path)
    if ng is None:
        with _lock:
            ng = _groups.get(path)
            if ng is None:
                from hailo_platform import (ConfigureParams, HEF,
                                            HailoStreamInterface)
                hef = HEF(path)
                cfg = ConfigureParams.create_from_hef(
                    hef, interface=HailoStreamInterface.PCIe)
                ng = get_vdevice().configure(hef, cfg)[0]
                _groups[path] = ng
    return ng


def shutdown():
    """공유 장치를 명시적으로 해제한다.

    평상시엔 부를 필요가 없다 — 프로세스 종료와 함께 정리된다.
    개별 detector 의 `close()` 는 **이 함수를 부르지 않는다**(다른 모델이 죽는다).
    """
    global _vdevice
    with _lock:
        _groups.clear()
        _vdevice = None
