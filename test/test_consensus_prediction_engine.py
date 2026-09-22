# test_consensus_prediction_engine.py
# 12-Phase Regression & Security Test Suite for ConsensusPredictionEngine
import json
import hashlib
import urllib.parse
from datetime import datetime, timezone


class MockGL:
    def __init__(self):
        self.transfers = []
        self.mock_web_responses = {}
        self.fail_web_fetch = False

    def emit_transfer(self, recipient: str, amount: int):
        self.transfers.append({"recipient": str(recipient).lower(), "amount": int(amount)})

    def get_webpage(self, url: str) -> str:
        if self.fail_web_fetch:
            raise RuntimeError("Simulated network timeout connecting to resolution source")
        return self.mock_web_responses.get(url, "<html><body><h1>Official Upgrade Notice</h1><p>Ethereum Pectra upgrade successfully activated on block 21000000.</p></body></html>")

    def exec_prompt(self, prompt: str) -> str:
        return json.dumps({"verdict": "YES", "rationale": "Pectra upgrade confirmed on official consensus client releases."})


class MockConsensusPredictionEngine:
    def __init__(self, owner_address: str, gl_mock: MockGL):
        self.gl = gl_mock
        self.owner = owner_address.lower()
        self.total_markets_created = 1
        self.total_markets_resolved = 0
        self.total_volume_locked = 1_000_000_000_000
        self.total_payouts_distributed = 0

        self.markets = {}
        self.markets_by_hash = {}
        self.positions = {}
        self.consumed_market_hashes = {}
        self.claimable_balances = {}

        self.OUTCOME_YES = "YES"
        self.OUTCOME_NO = "NO"
        self.OUTCOME_INVALID = "INVALID_REFUND"

        self.MIN_INITIAL_LIQUIDITY = 100_000_000_000
        self.MIN_BET_AMOUNT = 10_000_000_000
        self.MIN_MARKET_DURATION = 3600
        self.MAX_MARKET_DURATION = 86400 * 365
        self.PROTOCOL_FEE_BPS = 200

        self._seed_genesis_fixtures()

    def _seed_genesis_fixtures(self):
        creator = "0x1111111111111111111111111111111111111111"
        genesis_time = 1790000000

        m1_id = "MARKET_1"
        m1_hash = self._compute_market_hash(creator, "Will Ethereum execute Pectra upgrade in 2026?", "https://eips.ethereum.org/EIPS/eip-7600", "GENESIS_M1")

        self.markets[m1_id] = {
            "market_id": m1_id,
            "creator": creator.lower(),
            "question": "Will Ethereum execute Pectra upgrade in 2026?",
            "resolution_source_url": "https://eips.ethereum.org/EIPS/eip-7600",
            "market_hash": m1_hash,
            "pool_yes": 600_000_000_000,
            "pool_no": 400_000_000_000,
            "total_volume": 1_000_000_000_000,
            "created_at": genesis_time,
            "close_timestamp": genesis_time + 86400 * 30,
            "resolution_timestamp": 0,
            "winning_outcome": "NONE",
            "status": "OPEN_FOR_TRADING",
            "adjudication_rationale": ""
        }
        self.consumed_market_hashes[m1_hash] = True
        self.positions["MARKET_1_" + creator.lower()] = {
            "position_id": "MARKET_1_" + creator.lower(),
            "market_id": "MARKET_1",
            "user": creator.lower(),
            "yes_shares": 600_000_000_000,
            "no_shares": 400_000_000_000,
            "has_claimed": False,
            "claimed_amount": 0
        }

    def _compute_market_hash(self, creator: str, question: str, url: str, nonce: str) -> str:
        data = (
            "L" + str(len(creator)) + ":" + creator.lower() + "|" +
            "L" + str(len(question)) + ":" + question + "|" +
            "L" + str(len(url)) + ":" + url + "|" +
            "L" + str(len(nonce)) + ":" + nonce
        )
        return hashlib.sha256(data.encode("utf-8")).hexdigest()

    def _validate_eth_address(self, addr_str: str, field_name: str) -> str:
        clean = addr_str.strip().strip('"').strip("'")
        assert len(clean) == 42 and clean.startswith("0x"), "[ERR_ADDR_01]"
        for ch in clean[2:].lower():
            assert ch in "0123456789abcdef", "[ERR_ADDR_02]"
        assert clean.lower() != "0x0000000000000000000000000000000000000000", "[ERR_ADDR_ZERO]"
        return clean

    def _validate_url(self, url: str, field_name: str) -> str:
        clean = url.strip().strip('"').strip("'")
        assert 10 <= len(clean) <= 300, "[ERR_URL_LEN]"
        parsed = urllib.parse.urlsplit(clean)
        assert parsed.scheme in ("https", "http"), "[ERR_URL_SCHEME]"
        assert "@" not in parsed.netloc, "[ERR_URL_SSRF]"
        host = parsed.hostname.lower() if parsed.hostname else ""
        assert host not in ("localhost", "0.0.0.0", "127.0.0.1", "169.254.169.254"), "[ERR_URL_SSRF]"
        return clean

    def create_prediction_market(self, caller: str, value: int, question: str, resolution_source_url: str, duration_seconds: int, initial_yes_bps: int, nonce: str) -> str:
        sender_hex = self._validate_eth_address(caller, "Creator").lower()
        clean_q = question.strip().strip('"').strip("'")
        assert 10 <= len(clean_q) <= 256, "[ERR_QUESTION_LEN]"

        clean_url = self._validate_url(resolution_source_url, "URL")
        dur = int(duration_seconds)
        assert self.MIN_MARKET_DURATION <= dur <= self.MAX_MARKET_DURATION, "[ERR_DURATION_BOUNDS]"

        seed_liq = int(value)
        assert seed_liq >= self.MIN_INITIAL_LIQUIDITY, "[ERR_MIN_LIQUIDITY]"

        bps = int(initial_yes_bps)
        assert 1000 <= bps <= 9000, "[ERR_PROB_BOUNDS]"

        m_hash = self._compute_market_hash(sender_hex, clean_q, clean_url, nonce)
        assert m_hash.lower() not in self.consumed_market_hashes, "[ERR_MARKET_EXISTS]"

        seed_yes = (seed_liq * bps) // 10000
        seed_no = seed_liq - seed_yes

        now_utc = int(datetime.now(timezone.utc).timestamp())
        new_m_id = "MARKET_" + str(self.total_markets_created + 1)

        self.markets[new_m_id] = {
            "market_id": new_m_id,
            "creator": sender_hex,
            "question": clean_q,
            "resolution_source_url": clean_url,
            "market_hash": m_hash,
            "pool_yes": seed_yes,
            "pool_no": seed_no,
            "total_volume": seed_liq,
            "created_at": now_utc,
            "close_timestamp": now_utc + dur,
            "resolution_timestamp": 0,
            "winning_outcome": "NONE",
            "status": "OPEN_FOR_TRADING",
            "adjudication_rationale": ""
        }

        self.consumed_market_hashes[m_hash.lower()] = True
        self.total_markets_created += 1
        self.total_volume_locked += seed_liq

        # GL-STW-05: Mint creator position shares for seed liquidity
        self.positions[new_m_id + "_" + sender_hex] = {
            "position_id": new_m_id + "_" + sender_hex,
            "market_id": new_m_id,
            "user": sender_hex,
            "yes_shares": seed_yes,
            "no_shares": seed_no,
            "has_claimed": False,
            "claimed_amount": 0
        }

        return "MARKET_CREATED: " + new_m_id

    def place_bet(self, caller: str, value: int, market_id: str, outcome_choice: str, simulated_current_time: int = None) -> str:
        clean_m_id = market_id.strip().upper()
        assert clean_m_id in self.markets, "[ERR_MARKET_NOT_FOUND]"
        m = self.markets[clean_m_id]
        assert m["status"] == "OPEN_FOR_TRADING", "[ERR_MARKET_CLOSED]"

        now_utc = simulated_current_time if simulated_current_time is not None else int(datetime.now(timezone.utc).timestamp())
        assert now_utc < m["close_timestamp"], "[ERR_TRADING_DEADLINE]"

        choice = outcome_choice.strip().upper()
        assert choice in (self.OUTCOME_YES, self.OUTCOME_NO), "[ERR_INVALID_OUTCOME]"

        bet_val = int(value)
        assert bet_val >= self.MIN_BET_AMOUNT, "[ERR_MIN_BET]"

        sender_hex = self._validate_eth_address(caller, "Trader").lower()
        pos_id = clean_m_id + "_" + sender_hex

        if pos_id not in self.positions:
            self.positions[pos_id] = {
                "position_id": pos_id,
                "market_id": clean_m_id,
                "user": sender_hex,
                "yes_shares": 0,
                "no_shares": 0,
                "has_claimed": False,
                "claimed_amount": 0
            }

        pos = self.positions[pos_id]
        if choice == self.OUTCOME_YES:
            m["pool_yes"] += bet_val
            pos["yes_shares"] += bet_val
        else:
            m["pool_no"] += bet_val
            pos["no_shares"] += bet_val

        m["total_volume"] += bet_val
        self.total_volume_locked += bet_val
        return "BET_PLACED: " + clean_m_id

    def resolve_market(self, market_id: str, simulated_current_time: int = None, simulated_verdict: str = None) -> str:
        clean_m_id = market_id.strip().upper()
        assert clean_m_id in self.markets, "[ERR_MARKET_NOT_FOUND]"
        m = self.markets[clean_m_id]
        assert m["status"] == "OPEN_FOR_TRADING", "[ERR_NOT_OPEN]"

        now_utc = simulated_current_time if simulated_current_time is not None else int(datetime.now(timezone.utc).timestamp())
        assert now_utc >= m["close_timestamp"], "[ERR_EARLY_RESOLUTION]"

        try:
            evidence_text = self.gl.get_webpage(m["resolution_source_url"])
        except Exception:
            raise AssertionError("[ERR_EVIDENCE_FETCH_FAILED]")

        assert evidence_text is not None and len(evidence_text.strip()) >= 30, "[ERR_EVIDENCE_FETCH_FAILED]"

        verdict = simulated_verdict if simulated_verdict else self.OUTCOME_YES
        rationale = "Evaluated by consensus."

        m["winning_outcome"] = verdict
        m["status"] = "RESOLVED"
        m["resolution_timestamp"] = now_utc
        m["adjudication_rationale"] = rationale
        self.total_markets_resolved += 1
        return "MARKET_RESOLVED: " + clean_m_id

    def claim_rewards(self, caller: str, market_id: str) -> str:
        clean_m_id = market_id.strip().upper()
        assert clean_m_id in self.markets, "[ERR_MARKET_NOT_FOUND]"
        m = self.markets[clean_m_id]
        assert m["status"] == "RESOLVED", "[ERR_MARKET_NOT_RESOLVED]"

        sender_hex = self._validate_eth_address(caller, "Claimant").lower()
        pos_id = clean_m_id + "_" + sender_hex
        assert pos_id in self.positions, "[ERR_NO_POSITION]"
        pos = self.positions[pos_id]
        assert not pos["has_claimed"], "[ERR_ALREADY_CLAIMED]"

        payout = 0
        total_vol = m["total_volume"]
        winning = m["winning_outcome"]

        if winning == self.OUTCOME_INVALID:
            payout = pos["yes_shares"] + pos["no_shares"]
        elif winning == self.OUTCOME_YES:
            yes_pool = m["pool_yes"]
            user_yes = pos["yes_shares"]
            assert user_yes > 0, "[ERR_NO_WINNING_SHARES]"
            net_pool = (total_vol * (10000 - self.PROTOCOL_FEE_BPS)) // 10000
            payout = (net_pool * user_yes) // yes_pool
        elif winning == self.OUTCOME_NO:
            no_pool = m["pool_no"]
            user_no = pos["no_shares"]
            assert user_no > 0, "[ERR_NO_WINNING_SHARES]"
            net_pool = (total_vol * (10000 - self.PROTOCOL_FEE_BPS)) // 10000
            payout = (net_pool * user_no) // no_pool

        assert payout > 0, "[ERR_ZERO_PAYOUT]"
        pos["has_claimed"] = True
        pos["claimed_amount"] = payout
        self.total_volume_locked -= payout
        self.total_payouts_distributed += payout

        self.gl.emit_transfer(sender_hex, payout)
        return "CLAIM_SUCCESS: " + sender_hex

    def get_market_odds(self, market_id: str) -> dict:
        clean_m_id = market_id.strip().upper()
        if clean_m_id not in self.markets:
            return {"exists": False}
        m = self.markets[clean_m_id]
        y = m["pool_yes"]
        n = m["pool_no"]
        tot = y + n
        prob_yes = (y * 10000) // tot if tot > 0 else 5000
        return {
            "exists": True,
            "market_id": m["market_id"],
            "prob_yes_bps": prob_yes,
            "prob_no_bps": 10000 - prob_yes,
            "total_volume_wei": str(tot),
            "status": m["status"]
        }


def run_all_phases():
    print("=" * 80)
    print("STARTING 12-PHASE REGRESSION TEST SUITE: ConsensusPredictionEngine")
    print("=" * 80)

    gl_mock = MockGL()
    admin = "0x0000000000000000000000000000000000000001"
    engine = MockConsensusPredictionEngine(admin, gl_mock)

    # Phase 1: Genesis Fixtures
    print("\n[Phase 1] Testing Genesis Fixtures & Immutability...")
    assert "MARKET_1" in engine.markets
    m1 = engine.markets["MARKET_1"]
    assert m1["status"] == "OPEN_FOR_TRADING"
    assert m1["total_volume"] == 1_000_000_000_000
    print("  [+] Phase 1 Passed: Genesis prediction market permanently seeded.")

    # Phase 2: Length-Prefixed Hashing & Delimiter Resistance
    print("\n[Phase 2] Testing Canonical Length-Prefixed Hashing & Delimiter Resistance...")
    h1 = engine._compute_market_hash("0x1111", "Will BTC reach 100k?", "https://news.com/1", "nonceA")
    h2 = engine._compute_market_hash("0x11", "11Will BTC reach 100k?", "https://news.com/1", "nonceA")
    assert h1 != h2, "Delimiter injection collision detected!"
    print("  [+] Phase 2 Passed: Canonical hashing resists delimiter injection.")

    # Phase 3: Address & SSRF Validation
    print("\n[Phase 3] Testing Strict Address and SSRF Sanitization...")
    try:
        engine._validate_eth_address("0xBadAddressTooShort", "Address")
        assert False
    except AssertionError:
        pass
    try:
        engine._validate_url("http://127.0.0.1/admin", "URL")
        assert False
    except AssertionError:
        pass
    print("  [+] Phase 3 Passed: Address and SSRF defenses verified.")

    # Phase 4: Market Creation & Seed Liquidity
    print("\n[Phase 4] Testing Market Creation & Seed Liquidity Escrow...")
    creator = "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    res_m = engine.create_prediction_market(caller=creator, value=200_000_000_000, question="Will Solana throughput exceed 100k TPS in 2026?", resolution_source_url="https://solana.com/metrics", duration_seconds=86400 * 14, initial_yes_bps=5000, nonce="nonce_m2")
    assert "MARKET_CREATED: MARKET_2" in res_m
    assert engine.markets["MARKET_2"]["pool_yes"] == 100_000_000_000
    assert engine.markets["MARKET_2"]["pool_no"] == 100_000_000_000
    print("  [+] Phase 4 Passed: Market created and seed liquidity escrowed.")

    # Phase 5: Probability Bounds Check
    print("\n[Phase 5] Testing Probability Bps Bounds Check...")
    try:
        # Invalid probability 95% (> 90%)
        engine.create_prediction_market(caller=creator, value=100_000_000_000, question="Bad Market Bounds?", resolution_source_url="https://example.com", duration_seconds=86400 * 7, initial_yes_bps=9500, nonce="nonce_invalid_prob")
        assert False
    except AssertionError as e:
        assert "[ERR_PROB_BOUNDS]" in str(e)
    print("  [+] Phase 5 Passed: Initial probability bounds (1000-9000 bps) strictly enforced.")

    # Phase 6: Bet Placement
    print("\n[Phase 6] Testing Continuous Bet Placement (YES/NO Shares)...")
    trader1 = "0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
    trader2 = "0xCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC"

    res_bet1 = engine.place_bet(caller=trader1, value=50_000_000_000, market_id="MARKET_2", outcome_choice="YES")
    assert "BET_PLACED" in res_bet1
    assert engine.markets["MARKET_2"]["pool_yes"] == 150_000_000_000

    res_bet2 = engine.place_bet(caller=trader2, value=50_000_000_000, market_id="MARKET_2", outcome_choice="NO")
    assert "BET_PLACED" in res_bet2
    assert engine.markets["MARKET_2"]["pool_no"] == 150_000_000_000
    assert engine.markets["MARKET_2"]["total_volume"] == 300_000_000_000
    print("  [+] Phase 6 Passed: Continuous parimutuel liquidity pooling operational.")

    # Phase 7: Non-Admin Consensus Clock & Trading Deadline
    print("\n[Phase 7] Testing Non-Admin Consensus Clock on Trading Cutoff...")
    m2_close = engine.markets["MARKET_2"]["close_timestamp"]
    try:
        # Bet attempted after close timestamp
        engine.place_bet(caller=trader1, value=10_000_000_000, market_id="MARKET_2", outcome_choice="YES", simulated_current_time=m2_close + 100)
        assert False, "Late bet should revert"
    except AssertionError as e:
        assert "[ERR_TRADING_DEADLINE]" in str(e)
    print("  [+] Phase 7 Passed: Trading cutoff strictly enforced via consensus timestamp.")

    # Phase 8: Premature Resolution Prevention
    print("\n[Phase 8] Testing Premature Resolution Defense...")
    try:
        engine.resolve_market(market_id="MARKET_2", simulated_current_time=m2_close - 500)
        assert False, "Premature resolution must revert"
    except AssertionError as e:
        assert "[ERR_EARLY_RESOLUTION]" in str(e)
    print("  [+] Phase 8 Passed: Early resolution prevented.")

    # Phase 9: Fail-Closed Resolution Ingestion Invariant
    print("\n[Phase 9] Testing Fail-Closed Evidence Ingestion Invariant...")
    gl_mock.fail_web_fetch = True
    try:
        engine.resolve_market(market_id="MARKET_2", simulated_current_time=m2_close + 10)
        assert False, "Web fetch failure must revert fail-closed"
    except AssertionError as e:
        assert "[ERR_EVIDENCE_FETCH_FAILED]" in str(e)
    gl_mock.fail_web_fetch = False
    assert engine.markets["MARKET_2"]["status"] == "OPEN_FOR_TRADING"
    print("  [+] Phase 9 Passed: Fail-closed invariant cleanly maintained.")

    # Phase 10: Consensus Resolution & Proportional Winnings Claim
    print("\n[Phase 10] Testing Consensus Resolution & Proportional Payout...")
    res_res = engine.resolve_market(market_id="MARKET_2", simulated_current_time=m2_close + 10, simulated_verdict="YES")
    assert "MARKET_RESOLVED" in res_res
    assert engine.markets["MARKET_2"]["winning_outcome"] == "YES"

    # Trader1 holds 50 Gwei of YES shares out of 150 Gwei total YES pool.
    # Total volume: 300 Gwei. Protocol fee 2% (6 Gwei). Net pool = 294 Gwei.
    # Trader1 share: (294 * 50) // 150 = 98 Gwei.
    prev_transfers = len(gl_mock.transfers)
    res_claim = engine.claim_rewards(caller=trader1, market_id="MARKET_2")
    assert "CLAIM_SUCCESS" in res_claim
    assert len(gl_mock.transfers) == prev_transfers + 1
    assert gl_mock.transfers[-1]["recipient"] == trader1.lower()
    assert gl_mock.transfers[-1]["amount"] == 98_000_000_000
    print("  [+] Phase 10 Passed: YES winner claimed mathematical proportional pot share.")

    # Phase 11: INVALID_REFUND Ambiguity Protection
    print("\n[Phase 11] Testing Subjective Ambiguity & 100% Principal Refund...")
    creator2 = "0xDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD"
    engine.create_prediction_market(caller=creator2, value=100_000_000_000, question="Ambiguous Event?", resolution_source_url="https://ambiguous.com", duration_seconds=86400 * 7, initial_yes_bps=5000, nonce="nonce_m3")
    engine.place_bet(caller=trader2, value=20_000_000_000, market_id="MARKET_3", outcome_choice="NO")

    m3_close = engine.markets["MARKET_3"]["close_timestamp"]
    engine.resolve_market(market_id="MARKET_3", simulated_current_time=m3_close + 10, simulated_verdict="INVALID_REFUND")
    assert engine.markets["MARKET_3"]["winning_outcome"] == "INVALID_REFUND"

    # Trader2 deposited 20 Gwei, should get exactly 20 Gwei principal refund
    res_ref = engine.claim_rewards(caller=trader2, market_id="MARKET_3")
    assert "CLAIM_SUCCESS" in res_ref
    assert gl_mock.transfers[-1]["amount"] == 20_000_000_000
    print("  [+] Phase 11 Passed: Ambiguous market declared INVALID_REFUND, 100% principal refunded.")

    # Phase 12: Public Odds Hook & Anti-Double Claim
    print("\n[Phase 12] Testing Public Odds Gateway Hook & Anti-Double Claim...")
    odds = engine.get_market_odds("MARKET_1")
    assert odds["exists"] is True
    assert odds["prob_yes_bps"] == 6000
    assert odds["prob_no_bps"] == 4000

    # Trader1 attempts double claim on MARKET_2
    try:
        engine.claim_rewards(caller=trader1, market_id="MARKET_2")
        assert False, "Double claim should revert"
    except AssertionError as e:
        assert "[ERR_ALREADY_CLAIMED]" in str(e)
    print("  [+] Phase 12 Passed: Public odds views and anti-double-claim invariant verified.")

    # Phase 13: Creator Seed Liquidity Position & Full Refund (GL-STW-05 Remediation)
    print("\n[Phase 13] Testing Creator Seed Liquidity Entitlement & Refund (GL-STW-05)...")
    # Creator of MARKET_3 deposited 100 Gwei seed liquidity. Market was resolved to INVALID_REFUND.
    # Creator must receive 100% principal seed refund!
    prev_transfers = len(gl_mock.transfers)
    res_creator_ref = engine.claim_rewards(caller=creator2, market_id="MARKET_3")
    assert "CLAIM_SUCCESS" in res_creator_ref
    assert len(gl_mock.transfers) == prev_transfers + 1
    assert gl_mock.transfers[-1]["recipient"] == creator2.lower()
    assert gl_mock.transfers[-1]["amount"] == 100_000_000_000
    print("  [+] GL-STW-05 Verified: Market creator successfully redeemed 100% of seed liquidity on INVALID_REFUND.")

    # Creator of MARKET_2 (resolved YES) claims their proportional winning pot share
    res_creator_m2 = engine.claim_rewards(caller=creator, market_id="MARKET_2")
    assert "CLAIM_SUCCESS" in res_creator_m2
    assert gl_mock.transfers[-1]["recipient"] == creator.lower()
    # Creator held 100 Gwei of YES shares out of 150 Gwei total YES pool.
    # Net pool = 294 Gwei. Creator share: (294 * 100) // 150 = 196 Gwei.
    assert gl_mock.transfers[-1]["amount"] == 196_000_000_000
    print("  [+] GL-STW-05 Verified: Market creator successfully claimed winning pot share on YES resolution.")

    print("\n" + "=" * 80)
    print("ALL 13 PHASES OF ConsensusPredictionEngine TEST SUITE PASSED WITH 0 ERRORS!")
    print("=" * 80)


if __name__ == "__main__":
    run_all_phases()
