== ARCHITECTURE SPECIFICATION: CONSENSUS PREDICTION ENGINE ==

[1. MECHANISM CLASSIFICATION]
Parimutuel prediction market and multi-validator ambiguity settlement engine on GenLayer. Eliminates rigid oracles by enabling consensus to verify subjective or contested events.

[2. CONSENSUS & ESCROW GUARANTEES]
• Parimutuel Escrow: Traders pool native GEN into binary outcome shares via @gl.public.write.payable; winners claim mathematical pot shares via emit_transfer().
• Liquidity Rights: Market creators receive full position rights for seed capital, guaranteeing pot shares or 100% refund on invalid markets.
• Consensus Clock: Trading cutoff and resolution evaluate strictly against consensus UTC timestamps (datetime.now).
• Fail-Closed Ingestion: Web evidence timeouts trigger [ERR_EVIDENCE_FETCH_FAILED] with zero state mutation.
• Ambiguity Protection: Contested markets resolve to INVALID_REFUND, guaranteeing 100% principal return.
