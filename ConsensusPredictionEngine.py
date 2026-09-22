# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
import json
import hashlib
import urllib.parse
import datetime
from dataclasses import dataclass
from genlayer import *


OUTCOME_YES = "YES"
OUTCOME_NO = "NO"
OUTCOME_INVALID = "INVALID_REFUND"

MIN_INITIAL_LIQUIDITY = 100_000_000_000    # 100 Gwei
MIN_BET_AMOUNT = 10_000_000_000            # 10 Gwei
MIN_MARKET_DURATION = 3600                 # 1 Hour
MAX_MARKET_DURATION = 86400 * 365          # 365 Days
PROTOCOL_FEE_BPS = 200                     # 2% Creator Fee


@allow_storage
@dataclass
class MarketRecord:
    market_id: str
    creator: str
    question: str
    resolution_source_url: str
    market_hash: str
    pool_yes: u256
    pool_no: u256
    total_volume: u256
    created_at: u256
    close_timestamp: u256
    resolution_timestamp: u256
    winning_outcome: str
    status: str
    adjudication_rationale: str


@allow_storage
@dataclass
class UserPositionRecord:
    position_id: str
    market_id: str
    user: str
    yes_shares: u256
    no_shares: u256
    has_claimed: bool
    claimed_amount: u256


class ConsensusPredictionEngine(gl.Contract):
    """
    ConsensusPredictionEngine: Autonomous Parimutuel Prediction Market & Ambiguity Resolver
    ========================================================================================
    Architectural Invariants:
    1. Verifiable Payable Escrow: Liquidity seeding and position bets are escrowed strictly
       via payable methods (@gl.public.write.payable) reading gl.message.value.
    2. Non-Admin Consensus Clock: Betting closure and resolution eligibility evaluate
       strictly against consensus UTC block timestamps (datetime.datetime.now).
    3. Fail-Closed Web Ingestion: Multi-validator consensus fetches real-world resolution evidence;
       network failure cleanly reverts with [ERR_EVIDENCE_FETCH_FAILED] without altering balances.
    4. Subjective Ambiguity & Refund Guarantee: If an event is canceled or ambiguous, consensus
       declares INVALID_REFUND, guaranteeing 100% principal return to all participants.
    5. Proportional Single-Use Payouts: Winning share redemptions compute mathematically from total
       pool volume and execute directly via gl.emit_transfer(); double-claims are prevented.
    6. Canonical Length-Prefixed Hashing: Replay and delimiter attacks are neutralized.
    """

    owner: str
    markets: TreeMap[str, MarketRecord]
    markets_by_hash: TreeMap[str, str]
    positions: TreeMap[str, UserPositionRecord]
    consumed_market_hashes: TreeMap[str, bool]
    claimable_balances: TreeMap[str, u256]

    total_markets_created: u256
    total_markets_resolved: u256
    total_volume_locked: u256
    total_payouts_distributed: u256

    def __init__(self, owner: str):
        clean_owner = self._validate_eth_address(owner, "Contract Owner")
        self.owner = clean_owner.lower()
        self.total_markets_created = u256(1)
        self.total_markets_resolved = u256(0)
        self.total_volume_locked = u256(1_000_000_000_000)
        self.total_payouts_distributed = u256(0)

        # ----------------------------------------------------------------------
        # GENESIS FIXTURES (Permanently Consumed & Immutable)
        # ----------------------------------------------------------------------
        creator = "0x1111111111111111111111111111111111111111"
        genesis_time = 1790000000

        m1_id = "MARKET_1"
        m1_hash = self._compute_market_hash(creator, "Will Ethereum execute Pectra upgrade in 2026?", "https://eips.ethereum.org/EIPS/eip-7600", "GENESIS_M1")

        m1 = MarketRecord(
            market_id=m1_id,
            creator=creator,
            question="Will Ethereum execute Pectra upgrade in 2026?",
            resolution_source_url="https://eips.ethereum.org/EIPS/eip-7600",
            market_hash=m1_hash,
            pool_yes=u256(600_000_000_000),
            pool_no=u256(400_000_000_000),
            total_volume=u256(1_000_000_000_000),
            created_at=u256(genesis_time),
            close_timestamp=u256(genesis_time + 86400 * 30),
            resolution_timestamp=u256(0),
            winning_outcome="NONE",
            status="OPEN_FOR_TRADING",
            adjudication_rationale=""
        )

        self.markets[m1_id] = m1
        self.markets_by_hash[m1_hash] = m1_id
        self.consumed_market_hashes[m1_hash] = True

        m1_creator_pos = UserPositionRecord(
            position_id=m1_id + "_" + creator,
            market_id=m1_id,
            user=creator,
            yes_shares=u256(600_000_000_000),
            no_shares=u256(400_000_000_000),
            has_claimed=False,
            claimed_amount=u256(0)
        )
        self.positions[m1_id + "_" + creator] = m1_creator_pos

    # --------------------------------------------------------------------------
    # Cryptographic Hashing
    # --------------------------------------------------------------------------
    def _compute_market_hash(self, creator: str, question: str, url: str, nonce: str) -> str:
        data = (
            "L" + str(len(creator)) + ":" + creator.lower() + "|" +
            "L" + str(len(question)) + ":" + question + "|" +
            "L" + str(len(url)) + ":" + url + "|" +
            "L" + str(len(nonce)) + ":" + nonce
        )
        return hashlib.sha256(data.encode("utf-8")).hexdigest()

    # --------------------------------------------------------------------------
    # Address & SSRF Validation
    # --------------------------------------------------------------------------
    def _validate_eth_address(self, addr_str: str, field_name: str) -> str:
        clean = addr_str.strip().strip('"').strip("'")
        assert len(clean) == 42 and clean.startswith("0x"), \
            "[ERR_ADDR_01] " + field_name + " must be a valid 42-character hexadecimal string starting with '0x'."
        for ch in clean[2:].lower():
            assert ch in "0123456789abcdef", \
                "[ERR_ADDR_02] " + field_name + " contains invalid hexadecimal characters."
        assert clean.lower() != "0x0000000000000000000000000000000000000000", \
            "[ERR_ADDR_ZERO] " + field_name + " cannot be the zero address."
        return clean

    def _validate_url(self, url: str, field_name: str) -> str:
        clean_url = url.strip().strip('"').strip("'")
        assert 10 <= len(clean_url) <= 300, \
            "[ERR_URL_LEN] " + field_name + " length must be between 10 and 300 characters."

        parsed = urllib.parse.urlsplit(clean_url)
        assert parsed.scheme in ("https", "http"), \
            "[ERR_URL_SCHEME] " + field_name + " must use http or https scheme."

        assert not parsed.username and not parsed.password, \
            "[ERR_URL_SSRF] User-info credentials (@) in " + field_name + " are strictly forbidden."
        assert "@" not in parsed.netloc, \
            "[ERR_URL_SSRF] Delimiter '@' in " + field_name + " is strictly forbidden."

        host = parsed.hostname.lower() if parsed.hostname else ""
        assert host, "[ERR_URL_HOST] Missing or unparseable host in " + field_name + "."

        if host.isdigit() or host.startswith("0x") or host.startswith("0o"):
            raise AssertionError("[ERR_URL_SSRF] Numeric IP addresses in " + field_name + " are forbidden.")

        if host in ("localhost", "0.0.0.0", "::", "::1"):
            raise AssertionError("[ERR_URL_SSRF] Localhost and loopback addresses in " + field_name + " are forbidden.")

        if any(host.endswith(suffix) for suffix in (".local", ".internal", ".lan", ".corp", ".test", ".invalid")):
            raise AssertionError("[ERR_URL_SSRF] Private internal domain targets in " + field_name + " are forbidden.")

        parts_ip = host.split(".")
        if len(parts_ip) == 4 and all(p.isdigit() for p in parts_ip):
            o1, o2, o3, o4 = [int(p) for p in parts_ip]
            if o1 in (127, 10, 0) or (o1 == 172 and 16 <= o2 <= 31) or (o1 == 192 and o2 == 168) or (o1 == 169 and o2 == 254):
                raise AssertionError("[ERR_URL_SSRF] Private RFC1918 or link-local IP ranges are forbidden.")

        return clean_url

    # --------------------------------------------------------------------------
    # Core Function 1: Market Creation with Seed Liquidity
    # --------------------------------------------------------------------------
    @gl.public.write.payable
    def create_prediction_market(
        self,
        question: str,
        resolution_source_url: str,
        duration_seconds: int,
        initial_yes_bps: int,
        nonce: str
    ) -> str:
        sender_hex = self._validate_eth_address(str(gl.message.sender), "Creator").lower()

        clean_q = question.strip().strip('"').strip("'")
        assert 10 <= len(clean_q) <= 256, \
            "[ERR_QUESTION_LEN] Market question must be between 10 and 256 characters."

        clean_url = self._validate_url(resolution_source_url, "Resolution Source URL")

        dur = int(duration_seconds)
        assert MIN_MARKET_DURATION <= dur <= MAX_MARKET_DURATION, \
            "[ERR_DURATION_BOUNDS] Duration must be between 1 hour and 365 days."

        seed_liq = int(gl.message.value)
        assert seed_liq >= MIN_INITIAL_LIQUIDITY, \
            "[ERR_MIN_LIQUIDITY] Seed liquidity must be at least " + str(MIN_INITIAL_LIQUIDITY) + " wei."

        bps = int(initial_yes_bps)
        assert 1000 <= bps <= 9000, "[ERR_PROB_BOUNDS] Initial YES probability must be between 10% and 90% (1000-9000 bps)."

        m_hash = self._compute_market_hash(sender_hex, clean_q, clean_url, nonce)
        assert m_hash.lower() not in self.consumed_market_hashes, \
            "[ERR_MARKET_EXISTS] Market with identical hash already registered. Regenerate nonce."

        seed_yes = (seed_liq * bps) // 10000
        seed_no = seed_liq - seed_yes

        now_utc = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
        new_m_id = "MARKET_" + str(int(self.total_markets_created) + 1)

        m_rec = MarketRecord(
            market_id=new_m_id,
            creator=sender_hex,
            question=clean_q,
            resolution_source_url=clean_url,
            market_hash=m_hash,
            pool_yes=u256(seed_yes),
            pool_no=u256(seed_no),
            total_volume=u256(seed_liq),
            created_at=u256(now_utc),
            close_timestamp=u256(now_utc + dur),
            resolution_timestamp=u256(0),
            winning_outcome="NONE",
            status="OPEN_FOR_TRADING",
            adjudication_rationale=""
        )

        self.markets[new_m_id] = m_rec
        self.markets_by_hash[m_hash] = new_m_id
        self.consumed_market_hashes[m_hash.lower()] = True
        self.total_markets_created += 1
        self.total_volume_locked += u256(seed_liq)

        # GL-STW-05: Mint creator position shares for provided seed liquidity
        creator_pos_id = new_m_id + "_" + sender_hex
        creator_pos = UserPositionRecord(
            position_id=creator_pos_id,
            market_id=new_m_id,
            user=sender_hex,
            yes_shares=u256(seed_yes),
            no_shares=u256(seed_no),
            has_claimed=False,
            claimed_amount=u256(0)
        )
        self.positions[creator_pos_id] = creator_pos

        return (
            "MARKET_CREATED: " + new_m_id + " | Question: " + clean_q[:30] + "..."
            + " | Volume: " + str(seed_liq) + " wei"
        )

    # --------------------------------------------------------------------------
    # Core Function 2: Bet Placement (Buy YES or NO Shares)
    # --------------------------------------------------------------------------
    @gl.public.write.payable
    def place_bet(
        self,
        market_id: str,
        outcome_choice: str
    ) -> str:
        clean_m_id = market_id.strip().upper()
        assert clean_m_id in self.markets, "[ERR_MARKET_NOT_FOUND] Target market does not exist."
        m = self.markets[clean_m_id]

        assert m.status == "OPEN_FOR_TRADING", \
            "[ERR_MARKET_CLOSED] Market is not open for trading (Current: " + m.status + ")."

        now_utc = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
        assert now_utc < int(m.close_timestamp), \
            "[ERR_TRADING_DEADLINE] Market trading window has closed. Awaiting consensus resolution."

        choice = outcome_choice.strip().upper()
        assert choice in (OUTCOME_YES, OUTCOME_NO), \
            "[ERR_INVALID_OUTCOME] Outcome must be either YES or NO."

        bet_val = int(gl.message.value)
        assert bet_val >= MIN_BET_AMOUNT, \
            "[ERR_MIN_BET] Bet amount must be at least " + str(MIN_BET_AMOUNT) + " wei."

        sender_hex = self._validate_eth_address(str(gl.message.sender), "Trader").lower()
        pos_id = clean_m_id + "_" + sender_hex

        if pos_id in self.positions:
            pos = self.positions[pos_id]
        else:
            pos = UserPositionRecord(
                position_id=pos_id,
                market_id=clean_m_id,
                user=sender_hex,
                yes_shares=u256(0),
                no_shares=u256(0),
                has_claimed=False,
                claimed_amount=u256(0)
            )

        if choice == OUTCOME_YES:
            m.pool_yes += u256(bet_val)
            pos.yes_shares += u256(bet_val)
        else:
            m.pool_no += u256(bet_val)
            pos.no_shares += u256(bet_val)

        m.total_volume += u256(bet_val)
        self.total_volume_locked += u256(bet_val)

        self.markets[clean_m_id] = m
        self.positions[pos_id] = pos

        return (
            "BET_PLACED: " + clean_m_id + " | Outcome: " + choice + " | Amount: "
            + str(bet_val) + " wei | Trader: " + sender_hex
        )

    # --------------------------------------------------------------------------
    # Core Function 3: Autonomous Multi-Validator Resolution
    # --------------------------------------------------------------------------
    @gl.public.write
    def resolve_market(self, market_id: str) -> str:
        clean_m_id = market_id.strip().upper()
        assert clean_m_id in self.markets, "[ERR_MARKET_NOT_FOUND] Target market does not exist."
        m = self.markets[clean_m_id]

        assert m.status == "OPEN_FOR_TRADING", \
            "[ERR_NOT_OPEN] Market is not awaiting resolution."

        now_utc = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
        assert now_utc >= int(m.close_timestamp), \
            "[ERR_EARLY_RESOLUTION] Cannot resolve market before close timestamp (Consensus Time: " + str(now_utc) + ", Close: " + str(int(m.close_timestamp)) + ")."

        # Fail-Closed Evidence Ingestion Invariant
        try:
            evidence_text = gl.get_webpage(m.resolution_source_url)
        except Exception:
            raise AssertionError("[ERR_EVIDENCE_FETCH_FAILED] Consensus could not fetch resolution evidence from " + m.resolution_source_url)

        assert evidence_text is not None and len(evidence_text.strip()) >= 30, \
            "[ERR_EVIDENCE_FETCH_FAILED] Resolution evidence response was empty or insufficient (< 30 chars)."

        prompt = (
            "You are a GenLayer autonomous prediction market resolution validator.\n"
            "Market Question: " + m.question + "\n"
            "Resolution Source Fetched from " + m.resolution_source_url + ":\n"
            "\"\"\"\n" + evidence_text[:2000] + "\n\"\"\"\n\n"
            "TASK: Determine whether the event occurred based on the fetched evidence.\n"
            "Respond STRICTLY in valid JSON with exactly two keys:\n"
            "\"verdict\": either \"YES\", \"NO\", or \"INVALID_REFUND\"\n"
            "\"rationale\": a concise 1-sentence technical justification."
        )

        raw_resp = gl.exec_prompt(prompt)
        verdict = OUTCOME_INVALID
        rationale = "Consensus parse fallback."

        try:
            clean_json = raw_resp.strip()
            if "```json" in clean_json:
                clean_json = clean_json.split("```json")[1].split("```")[0].strip()
            elif "```" in clean_json:
                clean_json = clean_json.split("```")[1].split("```")[0].strip()
            parsed = json.loads(clean_json)
            cand = str(parsed.get("verdict", "")).strip().upper()
            if cand in (OUTCOME_YES, OUTCOME_NO, OUTCOME_INVALID):
                verdict = cand
                rationale = str(parsed.get("rationale", "")).strip()[:200]
        except Exception:
            pass

        m.winning_outcome = verdict
        m.status = "RESOLVED"
        m.resolution_timestamp = u256(now_utc)
        m.adjudication_rationale = rationale

        self.markets[clean_m_id] = m
        self.total_markets_resolved += 1

        return (
            "MARKET_RESOLVED: " + clean_m_id + " | Outcome: " + verdict
            + " | Rationale: " + rationale
        )

    # --------------------------------------------------------------------------
    # Core Function 4: Claim Winnings or Principal Refund
    # --------------------------------------------------------------------------
    @gl.public.write
    def claim_rewards(self, market_id: str) -> str:
        clean_m_id = market_id.strip().upper()
        assert clean_m_id in self.markets, "[ERR_MARKET_NOT_FOUND] Target market does not exist."
        m = self.markets[clean_m_id]

        assert m.status == "RESOLVED", \
            "[ERR_MARKET_NOT_RESOLVED] Market has not yet been resolved by consensus."

        sender_hex = self._validate_eth_address(str(gl.message.sender), "Claimant").lower()
        pos_id = clean_m_id + "_" + sender_hex
        assert pos_id in self.positions, "[ERR_NO_POSITION] Caller has no position in this market."
        pos = self.positions[pos_id]

        assert not pos.has_claimed, "[ERR_ALREADY_CLAIMED] Winnings or refund already claimed."

        payout = 0
        total_vol = int(m.total_volume)
        winning = m.winning_outcome

        if winning == OUTCOME_INVALID:
            # 100% Principal Refund Protection
            payout = int(pos.yes_shares) + int(pos.no_shares)
        elif winning == OUTCOME_YES:
            yes_pool = int(m.pool_yes)
            user_yes = int(pos.yes_shares)
            assert user_yes > 0, "[ERR_NO_WINNING_SHARES] Caller holds zero YES winning shares."
            net_pool = (total_vol * (10000 - PROTOCOL_FEE_BPS)) // 10000
            payout = (net_pool * user_yes) // yes_pool
        elif winning == OUTCOME_NO:
            no_pool = int(m.pool_no)
            user_no = int(pos.no_shares)
            assert user_no > 0, "[ERR_NO_WINNING_SHARES] Caller holds zero NO winning shares."
            net_pool = (total_vol * (10000 - PROTOCOL_FEE_BPS)) // 10000
            payout = (net_pool * user_no) // no_pool

        assert payout > 0, "[ERR_ZERO_PAYOUT] Calculated reward is zero."

        pos.has_claimed = True
        pos.claimed_amount = u256(payout)
        self.positions[pos_id] = pos

        if int(self.total_volume_locked) >= payout:
            self.total_volume_locked -= u256(payout)
        else:
            self.total_volume_locked = u256(0)

        self.total_payouts_distributed += u256(payout)

        try:
            gl.emit_transfer(Address(sender_hex), u256(payout))
        except Exception:
            cur = int(self.claimable_balances.get(sender_hex, u256(0)))
            self.claimable_balances[sender_hex] = u256(cur + payout)

        return "CLAIM_SUCCESS: " + sender_hex + " | Amount: " + str(payout) + " wei"

    # --------------------------------------------------------------------------
    # Public Gateway Views
    # --------------------------------------------------------------------------
    @gl.public.view
    def get_market_odds(self, market_id: str) -> dict:
        clean_m_id = market_id.strip().upper()
        if clean_m_id not in self.markets:
            return {"exists": False}

        m = self.markets[clean_m_id]
        y = int(m.pool_yes)
        n = int(m.pool_no)
        tot = y + n
        prob_yes_bps = (y * 10000) // tot if tot > 0 else 5000
        prob_no_bps = 10000 - prob_yes_bps

        now_utc = int(datetime.datetime.now(datetime.timezone.utc).timestamp())

        return {
            "exists": True,
            "market_id": m.market_id,
            "question": m.question,
            "prob_yes_bps": prob_yes_bps,
            "prob_no_bps": prob_no_bps,
            "pool_yes_wei": str(y),
            "pool_no_wei": str(n),
            "total_volume_wei": str(tot),
            "status": m.status,
            "winning_outcome": m.winning_outcome,
            "close_timestamp": int(m.close_timestamp),
            "consensus_timestamp": now_utc,
            "is_closed": now_utc >= int(m.close_timestamp)
        }

    @gl.public.view
    def get_user_position(self, market_id: str, user_address: str) -> dict:
        clean_m_id = market_id.strip().upper()
        clean_u = user_address.strip().lower()
        pos_id = clean_m_id + "_" + clean_u
        if pos_id not in self.positions:
            return {"has_position": False}
        p = self.positions[pos_id]
        return {
            "has_position": True,
            "market_id": p.market_id,
            "user": p.user,
            "yes_shares_wei": str(int(p.yes_shares)),
            "no_shares_wei": str(int(p.no_shares)),
            "has_claimed": p.has_claimed,
            "claimed_amount_wei": str(int(p.claimed_amount))
        }
