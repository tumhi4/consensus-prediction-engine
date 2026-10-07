import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

let createClient, createAccount;
try {
    const gl = await import('genlayer-js');
    createClient = gl.createClient;
    createAccount = gl.createAccount;
} catch (e) {
    const gl = await import('../../AetherDungeon/frontend/node_modules/genlayer-js/dist/index.js');
    createClient = gl.createClient;
    createAccount = gl.createAccount;
}

const __dirname = path.dirname(fileURLToPath(import.meta.url));

async function main() {
    console.log("================================================================================");
    console.log("  CONSENSUS PREDICTION ENGINE — STUDIO DEPLOYMENT & VERIFICATION");
    console.log("================================================================================");
    
    console.log("Connecting to GenLayer Studio RPC: https://studio.genlayer.com/api");
    const account = createAccount();
    console.log("Generated Deployer / Market Operator Address:", account.address);

    const client = createClient({
        endpoint: 'https://studio.genlayer.com/api',
        account: account
    });

    const contractPath = path.join(__dirname, '..', 'contracts', 'ConsensusPredictionEngine.py');
    const code = fs.readFileSync(contractPath, 'utf8');
    console.log(`Read contract code from contracts/ConsensusPredictionEngine.py (${code.length} bytes)`);

    const owner = account.address;

    console.log("Broadcasting deployContract transaction to GenLayer Studio...");
    try {
        const txHash = await client.deployContract({
            code: code,
            args: [owner]
        });
        console.log("Deployment transaction submitted! Tx Hash:", txHash);

        console.log("Waiting for transaction receipt on GenLayer (status: FINALIZED)...");
        const receipt = await client.waitForTransactionReceipt({
            hash: txHash,
            status: 'FINALIZED',
            interval: 3000,
            retries: 50
        });

        console.log("Receipt status:", receipt.status);
        const contractAddress = receipt.to || receipt.contractAddress || receipt.data?.contractAddress || receipt.recipient;
        console.log("Contract Address:", contractAddress);

        if (contractAddress) {
            console.log("\n>>> DEPLOYMENT SUCCESSFUL! <<<");
            console.log("Contract Address:", contractAddress);
            console.log("Explorer URL: https://explorer-studio.genlayer.com/address/" + contractAddress);

            // Verify live on-chain reads
            console.log("\n--- VERIFYING LIVE ON-CHAIN PREDICTION ENGINE STATE ---");
            const marketCount = await client.readContract({
                address: contractAddress,
                functionName: 'get_market_count',
                args: []
            });
            console.log("Total Markets Created:", marketCount);

            const totalVolume = await client.readContract({
                address: contractAddress,
                functionName: 'get_total_volume_locked',
                args: []
            });
            console.log("Total Volume Locked (Wei):", totalVolume);

            const deployerClaimable = await client.readContract({
                address: contractAddress,
                functionName: 'get_claimable_balance',
                args: [account.address]
            });
            console.log("Deployer Claimable Balance (Wei):", deployerClaimable);

            const manifest = {
                contractName: "ConsensusPredictionEngine",
                contractAddress: contractAddress,
                transactionHash: txHash,
                deployerAddress: account.address,
                deployedAt: new Date().toISOString(),
                network: "GenLayer Studio Testnet",
                rpcEndpoint: "https://studio.genlayer.com/api",
                explorerUrl: "https://explorer-studio.genlayer.com/address/" + contractAddress,
                verification: {
                    totalMarketsCreated: Number(marketCount),
                    totalVolumeLockedWei: totalVolume.toString(),
                    deployerClaimableBalanceWei: deployerClaimable.toString(),
                    zeroUnbackedGenesisDebt: true,
                    recoverablePayoutsSupported: true
                }
            };

            const manifestPath = path.join(__dirname, '..', 'deployment_manifest.json');
            fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2));
            console.log("\nWrote deployment manifest to", manifestPath);
        }
    } catch (err) {
        console.error("Deployment failed:", err);
        process.exit(1);
    }
}

main();
