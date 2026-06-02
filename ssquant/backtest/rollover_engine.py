# -*- coding: utf-8 -*-
"""
框架内自动换月（移仓）引擎：在策略回调前执行，按数据源独立状态机。

- simultaneous：同一次回调内连发平旧 +（可选）开新，不等成交。
- sequential：先发平旧，待旧腿平仓闭环后再发开新（reopen=False 时仅平旧）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from .rollover_audit import RolloverAuditLogger

if TYPE_CHECKING:
    from .live_trading_adapter import LiveTradingAdapter


@dataclass
class RolloverState:
    sent_for: Optional[str] = None
    expected_vol: int = 0
    expected_dir: Optional[str] = None
    wait_invocations: int = 0
    # sequential 专用：wait_close=等平旧成交；wait_open=已发开新、等净仓到位
    seq_phase: str = ""


_VALID_ROLL_MODES = frozenset({"simultaneous", "sequential"})


class RolloverEngine:
    def __init__(self, adapter: "LiveTradingAdapter"):
        self._adapter = adapter
        self._audit = RolloverAuditLogger(adapter.config)
        self._states: List[RolloverState] = []

    def _normalize_roll_mode(self, cfg: Dict[str, Any], ds_index: int, ds: Any) -> str:
        raw = (cfg.get("auto_roll_mode") or "simultaneous").strip().lower()
        if raw in _VALID_ROLL_MODES:
            return raw
        sym = getattr(ds, "symbol", "")
        self._adapter._log(
            f"[移仓] 数据源[{ds_index}] {sym} auto_roll_mode={raw!r} 无效，已按 simultaneous 处理"
        )
        return "simultaneous"

    def _resize(self) -> None:
        mds = self._adapter.multi_data_source
        if not mds:
            return
        n = len(mds.data_sources)
        while len(self._states) < n:
            self._states.append(RolloverState())
        if len(self._states) > n:
            self._states = self._states[:n]

    @staticmethod
    def _reset_state(st: RolloverState) -> None:
        st.sent_for = None
        st.expected_vol = 0
        st.expected_dir = None
        st.wait_invocations = 0
        st.seq_phase = ""

    def get_status_snapshot(self) -> Dict[str, Any]:
        """供 StrategyAPI 查询。"""
        self._resize()
        out: Dict[str, Any] = {}
        for i, st in enumerate(self._states):
            out[str(i)] = {
                "sent_for": st.sent_for,
                "expected_vol": st.expected_vol,
                "expected_dir": st.expected_dir,
                "wait_invocations": st.wait_invocations,
                "seq_phase": st.seq_phase,
            }
        return {"per_source": out}

    def process_before_strategy(self) -> None:
        self._resize()
        for i, ds in enumerate(self._adapter.multi_data_source.data_sources):
            cfg = getattr(ds, "config", None) or {}
            if not cfg.get("auto_roll_enabled", False):
                continue
            mode = self._normalize_roll_mode(cfg, i, ds)
            if mode == "sequential":
                self._process_ds_sequential(i, ds, cfg)
            else:
                self._process_ds_simultaneous(i, ds, cfg)

    def _should_complete(
        self,
        st: RolloverState,
        old_contract: Optional[str],
        pos: int,
        reopen: bool,
    ) -> bool:
        if old_contract:
            return False
        ev = int(st.expected_vol or 0)
        ed = st.expected_dir
        if not reopen:
            return pos == 0
        if ev <= 0 or ed not in ("long", "short"):
            return False
        if ed == "long":
            return pos == ev
        return pos == -ev

    def _emit_close_leg(
        self,
        ds: Any,
        pos: int,
        vol: int,
        ot: Any,
        close_ofs: Any,
        log_cb: Callable[..., None],
    ) -> None:
        if pos > 0:
            ds.sell(
                volume=vol,
                reason="roll_close_old_long",
                log_callback=log_cb,
                order_type=ot,
                offset_ticks=close_ofs,
            )
        else:
            ds.buycover(
                volume=vol,
                reason="roll_close_old_short",
                log_callback=log_cb,
                order_type=ot,
                offset_ticks=close_ofs,
            )

    def _emit_open_leg(
        self,
        ds: Any,
        st: RolloverState,
        vol: int,
        ot: Any,
        open_ofs: Any,
        log_cb: Callable[..., None],
    ) -> None:
        ed = st.expected_dir
        if ed == "long":
            ds.buy(
                volume=vol,
                reason="roll_open_new_long",
                log_callback=log_cb,
                order_type=ot,
                offset_ticks=open_ofs,
            )
        elif ed == "short":
            ds.sellshort(
                volume=vol,
                reason="roll_open_new_short",
                log_callback=log_cb,
                order_type=ot,
                offset_ticks=open_ofs,
            )

    def _process_ds_simultaneous(self, index: int, ds: Any, cfg: Dict[str, Any]) -> None:
        st = self._states[index]
        old_contract = getattr(ds, "_old_contract", None)
        pos = int(ds.get_current_pos()) if hasattr(ds, "get_current_pos") else 0
        reopen = bool(cfg.get("auto_roll_reopen", True))
        timeout = int(cfg.get("auto_roll_verify_timeout_bars", 500))

        log_cb = self._adapter._log

        if st.sent_for is not None:
            st.wait_invocations += 1
            if self._should_complete(st, old_contract, pos, reopen):
                self._audit.log(
                    "rollover_complete",
                    ds_index=index,
                    symbol=getattr(ds, "symbol", ""),
                    old_contract="",
                    pos=pos,
                )
                self._reset_state(st)
            elif st.wait_invocations > timeout:
                self._audit.log(
                    "rollover_timeout_reset",
                    ds_index=index,
                    symbol=getattr(ds, "symbol", ""),
                    wait_invocations=st.wait_invocations,
                )
                self._reset_state(st)
                log_cb(
                    f"[移仓] 超时（>{timeout} 次策略调用）未闭环，已重置移仓状态（数据源 {index}）"
                )
            return

        if not old_contract or pos == 0:
            return

        ot = cfg.get("auto_roll_order_type", "next_bar_open")
        close_ofs = cfg.get("auto_roll_close_offset_ticks")
        open_ofs = cfg.get("auto_roll_open_offset_ticks")
        vol = abs(pos)

        self._audit.log(
            "rollover_submit",
            ds_index=index,
            symbol=getattr(ds, "symbol", ""),
            old_contract=old_contract,
            pos=pos,
            reopen=reopen,
            order_type=ot,
            mode="simultaneous",
        )
        log_cb(
            f"[移仓] 数据源[{index}] {getattr(ds, 'symbol', '')} 旧合约={old_contract} 净持仓={pos} → 同根提交平旧"
            + ("+开新" if reopen else "（不开新）")
        )

        st.expected_vol = vol
        st.expected_dir = "long" if pos > 0 else "short"
        st.wait_invocations = 0
        st.seq_phase = ""

        self._emit_close_leg(ds, pos, vol, ot, close_ofs, log_cb)
        if reopen:
            self._emit_open_leg(ds, st, vol, ot, open_ofs, log_cb)

        st.sent_for = old_contract

    def _process_ds_sequential(self, index: int, ds: Any, cfg: Dict[str, Any]) -> None:
        st = self._states[index]
        old_contract = getattr(ds, "_old_contract", None)
        pos = int(ds.get_current_pos()) if hasattr(ds, "get_current_pos") else 0
        reopen = bool(cfg.get("auto_roll_reopen", True))
        timeout = int(cfg.get("auto_roll_verify_timeout_bars", 500))
        log_cb = self._adapter._log
        sym = getattr(ds, "symbol", "")

        ot = cfg.get("auto_roll_order_type", "next_bar_open")
        close_ofs = cfg.get("auto_roll_close_offset_ticks")
        open_ofs = cfg.get("auto_roll_open_offset_ticks")

        if st.sent_for is not None:
            st.wait_invocations += 1
            # 平旧已闭环、待补开新：仅发开新一次
            if (
                st.seq_phase == "wait_close"
                and reopen
                and old_contract is None
                and pos == 0
            ):
                vol = int(st.expected_vol or 0)
                if vol <= 0 or st.expected_dir not in ("long", "short"):
                    self._audit.log(
                        "rollover_sequential_open_skipped",
                        ds_index=index,
                        symbol=sym,
                        expected_vol=st.expected_vol,
                        expected_dir=st.expected_dir,
                        note="invalid state before open leg",
                    )
                    log_cb(
                        f"[移仓] 数据源[{index}] {sym} 平旧后无法开新（expected_vol/dir 异常），已重置"
                    )
                    self._reset_state(st)
                    return
                self._audit.log(
                    "rollover_submit_open",
                    ds_index=index,
                    symbol=sym,
                    pos=pos,
                    order_type=ot,
                    mode="sequential",
                )
                log_cb(
                    f"[移仓] 数据源[{index}] {sym} 平旧完成 → 提交开新（sequential）"
                )
                self._emit_open_leg(ds, st, vol, ot, open_ofs, log_cb)
                st.seq_phase = "wait_open"
                st.sent_for = sym or "__open__"
                return

            if self._should_complete(st, old_contract, pos, reopen):
                self._audit.log(
                    "rollover_complete",
                    ds_index=index,
                    symbol=sym,
                    old_contract="",
                    pos=pos,
                    mode="sequential",
                )
                self._reset_state(st)
            elif st.wait_invocations > timeout:
                self._audit.log(
                    "rollover_timeout_reset",
                    ds_index=index,
                    symbol=sym,
                    wait_invocations=st.wait_invocations,
                    mode="sequential",
                )
                self._reset_state(st)
                log_cb(
                    f"[移仓] 超时（>{timeout} 次策略调用）未闭环，已重置移仓状态（数据源 {index}）"
                )
            return

        if not old_contract or pos == 0:
            return

        vol = abs(pos)
        self._audit.log(
            "rollover_submit",
            ds_index=index,
            symbol=sym,
            old_contract=old_contract,
            pos=pos,
            reopen=reopen,
            order_type=ot,
            mode="sequential_close_only",
        )
        log_cb(
            f"[移仓] 数据源[{index}] {sym} 旧合约={old_contract} 净持仓={pos} → sequential 仅平旧"
            + ("（平后再开新）" if reopen else "（不开新）")
        )

        st.expected_vol = vol
        st.expected_dir = "long" if pos > 0 else "short"
        st.wait_invocations = 0
        st.seq_phase = "wait_close"
        self._emit_close_leg(ds, pos, vol, ot, close_ofs, log_cb)
        st.sent_for = old_contract
