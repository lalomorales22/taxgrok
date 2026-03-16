<?php
// Set more secure Content Security Policy that allows our inline styles/scripts but NO EVAL
header("Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; connect-src 'self' https://api.helius.xyz; img-src 'self' data:;");

// Allow longer execution time for AI generation (5 minutes)
set_time_limit(300);

// ============================================================
// SOLANA WALLET TRACKER - Phase 1
// Wallet management + transaction fetching via Helius API
// Stack: Single-file PHP + SQLite
// ============================================================

// --- CONFIGURATION ---
// Parse .env if exists
$envFile = __DIR__ . '/.env';
if (file_exists($envFile)) {
    $lines = file($envFile, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
    foreach ($lines as $line) {
        if (strpos(trim($line), '#') === 0) continue;
        list($name, $value) = explode('=', $line, 2);
        $value = trim($value);
        $value = trim($value, "\r\n\"'"); // Strip carriage returns and quotes
        putenv(trim($name) . '=' . $value);
        $_ENV[trim($name)] = $value;
    }
}
define('HELIUS_API_KEY', getenv('HELIUS_API_KEY') ?: ''); 
define('DB_PATH', __DIR__ . '/soltracker.db');
define('HELIUS_BASE', 'https://api.helius.xyz');
define('TX_PER_PAGE', 50);

// --- DATABASE SETUP ---
function getDB()
{
    static $db = null;
    if ($db === null) {
        $db = new SQLite3(DB_PATH);
        $db->busyTimeout(5000);
        $db->exec('PRAGMA journal_mode=WAL');
        $db->exec('PRAGMA foreign_keys=ON');

        $db->exec("CREATE TABLE IF NOT EXISTS wallets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            address TEXT UNIQUE NOT NULL,
            label TEXT DEFAULT '',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_synced DATETIME DEFAULT NULL,
            tx_count INTEGER DEFAULT 0
        )");

        $db->exec("CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet_id INTEGER NOT NULL,
            signature TEXT UNIQUE NOT NULL,
            timestamp INTEGER NOT NULL,
            type TEXT DEFAULT 'UNKNOWN',
            description TEXT DEFAULT '',
            fee_sol REAL DEFAULT 0,
            source TEXT DEFAULT '',
            from_address TEXT DEFAULT '',
            to_address TEXT DEFAULT '',
            amount REAL DEFAULT 0,
            token_symbol TEXT DEFAULT 'SOL',
            token_mint TEXT DEFAULT '',
            native_transfers_json TEXT DEFAULT '[]',
            token_transfers_json TEXT DEFAULT '[]',
            raw_json TEXT DEFAULT '{}',
            FOREIGN KEY (wallet_id) REFERENCES wallets(id) ON DELETE CASCADE
        )");

        $db->exec("CREATE INDEX IF NOT EXISTS idx_tx_wallet ON transactions(wallet_id)");
        $db->exec("CREATE INDEX IF NOT EXISTS idx_tx_timestamp ON transactions(timestamp DESC)");
        $db->exec("CREATE INDEX IF NOT EXISTS idx_tx_signature ON transactions(signature)");
        $db->exec("CREATE INDEX IF NOT EXISTS idx_tx_type ON transactions(type)");
    }
    return $db;
}

// --- HELIUS API ---
function heliusFetch($endpoint, $params = [])
{
    if (empty(HELIUS_API_KEY)) {
        return ['error' => 'Helius API key not configured. Edit the HELIUS_API_KEY constant at the top of index.php.'];
    }
    $params['api-key'] = HELIUS_API_KEY;
    $url = HELIUS_BASE . $endpoint . '?' . http_build_query($params);

    $ch = curl_init($url);
    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT => 30,
        CURLOPT_HTTPHEADER => ['Accept: application/json'],
        CURLOPT_SSL_VERIFYPEER => true,
    ]);
    $response = curl_exec($ch);
    $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $error = curl_error($ch);

    if ($error)
        return ['error' => "cURL error: $error"];
    if ($httpCode !== 200)
        return ['error' => "Helius API returned HTTP $httpCode", 'body' => $response];

    return json_decode($response, true);
}

function fetchWalletTransactions($address, $beforeSignature = null)
{
    $params = ['limit' => 100];
    if ($beforeSignature) {
        $params['before'] = $beforeSignature;
    }

    $endpoint = "/v0/addresses/{$address}/transactions";
    return heliusFetch($endpoint, $params);
}

function syncWallet($walletId, $address)
{
    $db = getDB();

    // get the latest signature we already have
    $stmt = $db->prepare("SELECT signature FROM transactions WHERE wallet_id = :wid ORDER BY timestamp DESC LIMIT 1");
    $stmt->bindValue(':wid', $walletId, SQLITE3_INTEGER);
    $result = $stmt->execute()->fetchArray(SQLITE3_ASSOC);
    $latestSig = $result ? $result['signature'] : null;

    $allTx = [];
    $before = null;
    $maxPages = 20; // safety limit - 2000 tx max per sync
    $page = 0;
    $hitExisting = false;

    while ($page < $maxPages) {
        $batch = fetchWalletTransactions($address, $before);

        if (isset($batch['error']))
            return $batch;
        if (empty($batch))
            break;

        foreach ($batch as $tx) {
            // if we've reached a transaction we already have, stop
            if ($latestSig && $tx['signature'] === $latestSig) {
                $hitExisting = true;
                break 2;
            }
            $allTx[] = $tx;
        }

        // get the last signature for pagination
        $lastTx = end($batch);
        $before = $lastTx['signature'];
        $page++;

        // small delay to be nice to the API
        usleep(100000); // 100ms
    }

    // insert transactions into DB (newest first, so we reverse for chronological insert)
    $inserted = 0;
    $db->exec('BEGIN TRANSACTION');

    foreach (array_reverse($allTx) as $tx) {
        $sig = $tx['signature'] ?? '';
        if (empty($sig))
            continue;

        // parse the transaction data
        $type = $tx['type'] ?? 'UNKNOWN';
        $desc = $tx['description'] ?? '';
        $timestamp = $tx['timestamp'] ?? 0;
        $fee = ($tx['fee'] ?? 0) / 1e9; // lamports to SOL
        $source = $tx['source'] ?? '';

        // extract native (SOL) transfers
        $nativeTransfers = $tx['nativeTransfers'] ?? [];
        $tokenTransfers = $tx['tokenTransfers'] ?? [];

        // figure out primary from/to/amount
        $fromAddr = '';
        $toAddr = '';
        $amount = 0;
        $tokenSymbol = 'SOL';
        $tokenMint = '';

        // check token transfers first (more specific)
        if (!empty($tokenTransfers)) {
            $primary = $tokenTransfers[0];
            $fromAddr = $primary['fromUserAccount'] ?? '';
            $toAddr = $primary['toUserAccount'] ?? '';
            $amount = $primary['tokenAmount'] ?? 0;
            $tokenSymbol = $primary['symbol'] ?? $primary['mint'] ?? 'UNKNOWN';
            $tokenMint = $primary['mint'] ?? '';
        } elseif (!empty($nativeTransfers)) {
            $primary = $nativeTransfers[0];
            $fromAddr = $primary['fromUserAccount'] ?? '';
            $toAddr = $primary['toUserAccount'] ?? '';
            $amount = ($primary['amount'] ?? 0) / 1e9;
            $tokenSymbol = 'SOL';
        }

        $stmt = $db->prepare("INSERT OR IGNORE INTO transactions 
            (wallet_id, signature, timestamp, type, description, fee_sol, source, 
             from_address, to_address, amount, token_symbol, token_mint,
             native_transfers_json, token_transfers_json, raw_json)
            VALUES (:wid, :sig, :ts, :type, :desc, :fee, :src, 
                    :from, :to, :amt, :sym, :mint, :ntj, :ttj, :raw)");

        $stmt->bindValue(':wid', $walletId, SQLITE3_INTEGER);
        $stmt->bindValue(':sig', $sig, SQLITE3_TEXT);
        $stmt->bindValue(':ts', $timestamp, SQLITE3_INTEGER);
        $stmt->bindValue(':type', $type, SQLITE3_TEXT);
        $stmt->bindValue(':desc', $desc, SQLITE3_TEXT);
        $stmt->bindValue(':fee', $fee, SQLITE3_FLOAT);
        $stmt->bindValue(':src', $source, SQLITE3_TEXT);
        $stmt->bindValue(':from', $fromAddr, SQLITE3_TEXT);
        $stmt->bindValue(':to', $toAddr, SQLITE3_TEXT);
        $stmt->bindValue(':amt', $amount, SQLITE3_FLOAT);
        $stmt->bindValue(':sym', $tokenSymbol, SQLITE3_TEXT);
        $stmt->bindValue(':mint', $tokenMint, SQLITE3_TEXT);
        $stmt->bindValue(':ntj', json_encode($nativeTransfers), SQLITE3_TEXT);
        $stmt->bindValue(':ttj', json_encode($tokenTransfers), SQLITE3_TEXT);
        $stmt->bindValue(':raw', json_encode($tx), SQLITE3_TEXT);

        if ($stmt->execute())
            $inserted++;
    }

    // update wallet metadata
    $countStmt = $db->prepare("SELECT COUNT(*) as cnt FROM transactions WHERE wallet_id = :wid");
    $countStmt->bindValue(':wid', $walletId, SQLITE3_INTEGER);
    $totalTx = $countStmt->execute()->fetchArray(SQLITE3_ASSOC)['cnt'];

    $updateStmt = $db->prepare("UPDATE wallets SET last_synced = CURRENT_TIMESTAMP, tx_count = :cnt WHERE id = :wid");
    $updateStmt->bindValue(':cnt', $totalTx, SQLITE3_INTEGER);
    $updateStmt->bindValue(':wid', $walletId, SQLITE3_INTEGER);
    $updateStmt->execute();

    $db->exec('COMMIT');

    return [
        'success' => true,
        'new_transactions' => $inserted,
        'total_transactions' => $totalTx,
        'pages_fetched' => $page,
        'hit_existing' => $hitExisting,
    ];
}

// --- API ROUTER ---
if (isset($_GET['action']) || isset($_POST['action'])) {
    header('Content-Type: application/json');
    $action = $_GET['action'] ?? $_POST['action'] ?? '';
    $db = getDB();

    switch ($action) {

        // --- WALLET OPERATIONS ---
        case 'add_wallet':
            $address = trim($_POST['address'] ?? '');
            $label = trim($_POST['label'] ?? '');

            if (empty($address)) {
                echo json_encode(['error' => 'Wallet address is required']);
                exit;
            }

            // basic solana address validation (base58, 32-44 chars)
            if (!preg_match('/^[1-9A-HJ-NP-Za-km-z]{32,44}$/', $address)) {
                echo json_encode(['error' => 'Invalid Solana wallet address']);
                exit;
            }

            $stmt = $db->prepare("INSERT OR IGNORE INTO wallets (address, label) VALUES (:addr, :label)");
            $stmt->bindValue(':addr', $address, SQLITE3_TEXT);
            $stmt->bindValue(':label', $label ?: substr($address, 0, 4) . '...' . substr($address, -4), SQLITE3_TEXT);

            if ($stmt->execute() && $db->changes() > 0) {
                $id = $db->lastInsertRowID();
                echo json_encode([
                    'success' => true,
                    'wallet' => [
                        'id' => $id,
                        'address' => $address,
                        'label' => $label ?: substr($address, 0, 4) . '...' . substr($address, -4),
                        'tx_count' => 0,
                        'last_synced' => null
                    ]
                ]);
            } else {
                echo json_encode(['error' => 'Wallet already exists']);
            }
            exit;

        case 'delete_wallet':
            $id = intval($_POST['id'] ?? 0);
            if ($id <= 0) {
                echo json_encode(['error' => 'Invalid wallet ID']);
                exit;
            }

            $stmt = $db->prepare("DELETE FROM wallets WHERE id = :id");
            $stmt->bindValue(':id', $id, SQLITE3_INTEGER);
            $stmt->execute();
            echo json_encode(['success' => true]);
            exit;

        case 'list_wallets':
            $results = $db->query("SELECT * FROM wallets ORDER BY created_at DESC");
            $wallets = [];
            while ($row = $results->fetchArray(SQLITE3_ASSOC)) {
                $wallets[] = $row;
            }
            echo json_encode($wallets);
            exit;

        case 'update_wallet_label':
            $id = intval($_POST['id'] ?? 0);
            $label = trim($_POST['label'] ?? '');
            if ($id <= 0 || empty($label)) {
                echo json_encode(['error' => 'Invalid input']);
                exit;
            }

            $stmt = $db->prepare("UPDATE wallets SET label = :label WHERE id = :id");
            $stmt->bindValue(':label', $label, SQLITE3_TEXT);
            $stmt->bindValue(':id', $id, SQLITE3_INTEGER);
            $stmt->execute();
            echo json_encode(['success' => true]);
            exit;

        // --- SYNC / FETCH ---
        case 'sync_wallet':
            $id = intval($_POST['id'] ?? 0);
            if ($id <= 0) {
                echo json_encode(['error' => 'Invalid wallet ID']);
                exit;
            }

            $stmt = $db->prepare("SELECT address FROM wallets WHERE id = :id");
            $stmt->bindValue(':id', $id, SQLITE3_INTEGER);
            $row = $stmt->execute()->fetchArray(SQLITE3_ASSOC);
            if (!$row) {
                echo json_encode(['error' => 'Wallet not found']);
                exit;
            }

            $result = syncWallet($id, $row['address']);
            echo json_encode($result);
            exit;

        // --- TRANSACTION LISTING ---
        case 'list_transactions':
            $walletId = intval($_GET['wallet_id'] ?? 0);
            $page = max(1, intval($_GET['page'] ?? 1));
            $typeFilter = $_GET['type'] ?? '';
            $search = trim($_GET['search'] ?? '');
            $offset = ($page - 1) * TX_PER_PAGE;

            $where = "WHERE wallet_id = :wid";
            $params = [':wid' => $walletId];

            if ($typeFilter && $typeFilter !== 'ALL') {
                $where .= " AND type = :type";
                $params[':type'] = $typeFilter;
            }
            if ($search) {
                $where .= " AND (signature LIKE :s OR description LIKE :s OR from_address LIKE :s OR to_address LIKE :s OR token_symbol LIKE :s)";
                $params[':s'] = "%$search%";
            }

            // fetch wallet address for sum calculations
            $addrStmt = $db->prepare("SELECT address FROM wallets WHERE id = :wid");
            $addrStmt->bindValue(':wid', $walletId, SQLITE3_INTEGER);
            $walletAddr = $addrStmt->execute()->fetchArray(SQLITE3_ASSOC)['address'] ?? '';

            // count
            $countSql = "SELECT COUNT(*) as cnt FROM transactions $where";
            $countStmt = $db->prepare($countSql);
            foreach ($params as $k => $v)
                $countStmt->bindValue($k, $v);
            $total = $countStmt->execute()->fetchArray(SQLITE3_ASSOC)['cnt'];

            // fetch
            $sql = "SELECT id, signature, timestamp, type, description, fee_sol, source, 
                           from_address, to_address, amount, token_symbol, token_mint,
                           native_transfers_json, token_transfers_json
                    FROM transactions $where 
                    ORDER BY timestamp DESC 
                    LIMIT :limit OFFSET :offset";
            $stmt = $db->prepare($sql);
            foreach ($params as $k => $v)
                $stmt->bindValue($k, $v);
            $stmt->bindValue(':limit', TX_PER_PAGE, SQLITE3_INTEGER);
            $stmt->bindValue(':offset', $offset, SQLITE3_INTEGER);

            $results = $stmt->execute();
            $transactions = [];
            while ($row = $results->fetchArray(SQLITE3_ASSOC)) {
                $row['native_transfers'] = json_decode($row['native_transfers_json'], true);
                $row['token_transfers'] = json_decode($row['token_transfers_json'], true);
                unset($row['native_transfers_json'], $row['token_transfers_json']);
                $transactions[] = $row;
            }

            // get unique types for filter dropdown
            $typesStmt = $db->prepare("SELECT DISTINCT type FROM transactions WHERE wallet_id = :wid ORDER BY type");
            $typesStmt->bindValue(':wid', $walletId, SQLITE3_INTEGER);
            $typesRes = $typesStmt->execute();
            $types = [];
            while ($r = $typesRes->fetchArray(SQLITE3_ASSOC))
                $types[] = $r['type'];

            // calculate summary across all filtered transactions
            $sumSql = "SELECT 
                SUM(CASE WHEN token_symbol = 'SOL' AND LOWER(to_address) = LOWER(:waddr) THEN amount ELSE 0 END) as sol_in,
                SUM(CASE WHEN token_symbol = 'SOL' AND LOWER(to_address) != LOWER(:waddr) THEN amount ELSE 0 END) as sol_out,
                SUM(fee_sol) as total_fees
            FROM transactions $where";
            $sumStmt = $db->prepare($sumSql);
            foreach ($params as $k => $v) $sumStmt->bindValue($k, $v);
            $sumStmt->bindValue(':waddr', $walletAddr, SQLITE3_TEXT);
            $sumRes = $sumStmt->execute()->fetchArray(SQLITE3_ASSOC);
            
            $summary = [
                'sol_in' => $sumRes['sol_in'] ?? 0,
                'sol_out' => $sumRes['sol_out'] ?? 0,
                'net_sol' => ($sumRes['sol_in'] ?? 0) - ($sumRes['sol_out'] ?? 0),
                'total_fees' => $sumRes['total_fees'] ?? 0,
            ];

            echo json_encode([
                'transactions' => $transactions,
                'total' => $total,
                'page' => $page,
                'pages' => ceil($total / TX_PER_PAGE),
                'types' => $types,
                'summary' => $summary,
            ]);
            exit;

        // --- CSV EXPORT ---
        case 'export_csv':
            $walletId = intval($_GET['wallet_id'] ?? 0);
            if ($walletId <= 0) {
                echo json_encode(['error' => 'Invalid wallet']);
                exit;
            }

            $wStmt = $db->prepare("SELECT address, label FROM wallets WHERE id = :id");
            $wStmt->bindValue(':id', $walletId, SQLITE3_INTEGER);
            $wallet = $wStmt->execute()->fetchArray(SQLITE3_ASSOC);

            header('Content-Type: text/csv');
            header('Content-Disposition: attachment; filename="solana_tx_' . substr($wallet['address'], 0, 8) . '_' . date('Y-m-d') . '.csv"');

            $out = fopen('php://output', 'w');
            fputcsv($out, ['Date', 'Time (UTC)', 'Type', 'Description', 'From', 'To', 'Amount', 'Token', 'Fee (SOL)', 'Signature', 'Source'], ",", "\"", "");

            $stmt = $db->prepare("SELECT * FROM transactions WHERE wallet_id = :wid ORDER BY timestamp ASC");
            $stmt->bindValue(':wid', $walletId, SQLITE3_INTEGER);
            $results = $stmt->execute();

            $totalIn = 0;
            $totalOut = 0;

            while ($row = $results->fetchArray(SQLITE3_ASSOC)) {
                $amt = (float)$row['amount'];
                $isReceive = strtolower($row['to_address'] ?? '') === strtolower($wallet['address']);
                
                if ($row['token_symbol'] === 'SOL') {
                    if ($isReceive) {
                        $totalIn += $amt;
                    } else {
                        $totalOut += $amt;
                    }
                }

                fputcsv($out, [
                    date('Y-m-d', $row['timestamp']),
                    date('H:i:s', $row['timestamp']),
                    $row['type'],
                    $row['description'],
                    $row['from_address'],
                    $row['to_address'],
                    $row['amount'],
                    $row['token_symbol'],
                    $row['fee_sol'],
                    $row['signature'],
                    $row['source'],
                ], ",", "\"", "");
            }
            
            fputcsv($out, ['', '', '', '', '', '', '', '', '', '', ''], ",", "\"", "");
            fputcsv($out, ['Total SOL In', $totalIn, '', '', '', '', '', '', '', '', ''], ",", "\"", "");
            fputcsv($out, ['Total SOL Out', $totalOut, '', '', '', '', '', '', '', '', ''], ",", "\"", "");
            fputcsv($out, ['Net SOL', $totalIn - $totalOut, '', '', '', '', '', '', '', '', ''], ",", "\"", "");

            fclose($out);
            exit;

        // --- TAXGROK INTEGRATION ---
        case 'run_taxgrok':
            // Configure upload directory
            $uploadDir = __DIR__ . '/uploads/';
            if (!is_dir($uploadDir)) {
                mkdir($uploadDir, 0777, true);
            }

            // Clean up previous uploads
            $files = glob($uploadDir . '*');
            foreach ($files as $file) {
                if (is_file($file)) {
                    unlink($file);
                }
            }

            $taxpayerName = $_POST['taxpayer_name'] ?? 'User';
            $filingStatus = $_POST['filing_status'] ?? 'Unknown';
            
            // Handle file uploads
            $uploadedFiles = [];
            if (!empty($_FILES['documents']['name'][0])) {
                foreach ($_FILES['documents']['name'] as $key => $name) {
                    $tmpName = $_FILES['documents']['tmp_name'][$key];
                    $error = $_FILES['documents']['error'][$key];
                    
                    if ($error === UPLOAD_ERR_OK) {
                        $safeName = preg_replace('/[^a-zA-Z0-9.\-_]/', '_', $name);
                        $destination = $uploadDir . $safeName;
                        if (move_uploaded_file($tmpName, $destination)) {
                            $uploadedFiles[] = escapeshellarg($destination);
                        }
                    }
                }
            }

            if (empty($uploadedFiles)) {
                echo json_encode(['error' => 'No valid documents were uploaded.']);
                exit;
            }

            // Construct the command
            // Assuming taxgrok is installed in the local environment
            // Using a simple command string, but we need to inject the inputs via stdin or args.
            // Since taxgrok uses an interactive menu, we'll try to run it via python directly if it accepts args, 
            // OR we'll write a Python wrapper script to bypass the interactive menu.
            
            // Create a wrapper script to run taxgrok programmatically
            $wrapperPath = $uploadDir . 'run_wrapper.py';
            $wrapperCode = <<<PYTHON
import os
import sys
import traceback
from pathlib import Path

from taxgrok.config import load_runtime_config
from taxgrok.pipeline import run_phase3_pipeline
from taxgrok.report import write_phase3_report
from taxgrok.taxpayer import TaxpayerContext

try:
    files_to_process = [Path(p) for p in sys.argv[1:]]
    name = os.environ.get('USER_NAME', 'User')
    status = os.environ.get('USER_STATUS', 'unknown')

    config = load_runtime_config(
        username_override=name,
        output_dir=os.getcwd(),  # Output in the working directory
        verbose=False,
        require_api_key=True
    )
    # Force the user requested model explicitly after loading config
    from dataclasses import replace
    config = replace(config, model="grok-4-fast-reasoning")
    
    context = TaxpayerContext(display_name=name, filing_status=status)

    # Run pipeline
    result = run_phase3_pipeline(
        config=config,
        queued_files=files_to_process,
        report_writer=write_phase3_report,
        taxpayer_context=context
    )
    print(f"Report written: {result.report_path}")
except Exception as exc:
    print(f"Error: Pipeline failed: {exc}")
    traceback.print_exc()
    sys.exit(1)
PYTHON;
            file_put_contents($wrapperPath, $wrapperCode);

            // Set up environment mapping 
            // the PHP app must have XAI_API_KEY available from its own env or config
            $env = [
                'USER_NAME' => $taxpayerName,
                'USER_STATUS' => $filingStatus
            ];
            
            // Check if the user POSTed an API key from the frontend
            $postedApiKey = trim($_POST['xai_api_key'] ?? '');
            
            if (!empty($postedApiKey)) {
                 $env['XAI_API_KEY'] = $postedApiKey;
            } else {
                // Try to pull api key from system env
                if (getenv('XAI_API_KEY')) {
                    $env['XAI_API_KEY'] = getenv('XAI_API_KEY');
                } else {
                    // Look in parent dir .env if exists
                if (file_exists(dirname(__DIR__) . '/.env')) {
                    $lines = file(dirname(__DIR__) . '/.env', FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
                    foreach ($lines as $line) {
                        if (strpos(trim($line), '#') === 0) continue;
                        list($name, $value) = explode('=', $line, 2);
                        if (trim($name) === 'XAI_API_KEY') {
                            $value = trim($value);
                            $env['XAI_API_KEY'] = trim($value, "\r\n\"'"); // Strip carriage returns and quotes
                            break;
                        }
                    }
                }
                }
            }

            if (!isset($env['XAI_API_KEY'])) {
                 echo json_encode(['error' => 'XAI_API_KEY not found in environment or .env file. Please configure it for taxgrok to function.']);
                 exit;
            }

            // Build bash command wrapped with env variables
            $envStr = '';
            foreach ($env as $k => $v) {
                // Do not escape the Key otherwise shells cannot evaluate env variables
                $envStr .= $k . '=' . escapeshellarg($v) . ' ';
            }

            $pythonExec = 'python3'; // Assuming python3 is available in PATH
            // Use the venv if it exists
            if (file_exists(dirname(__DIR__) . '/.venv/bin/python3')) {
                $pythonExec = dirname(__DIR__) . '/.venv/bin/python3';
            }

            // Execute the wrapper
            $fileArgs = implode(' ', $uploadedFiles);
            $cmd = "cd " . escapeshellarg(dirname(__DIR__)) . " && env $envStr $pythonExec " . escapeshellarg($wrapperPath) . " $fileArgs 2>&1";
            
            $output = shell_exec($cmd);

            // Taxgrok writes "TAXGROK-<username>.md" to the working directory.
            $reportFiles = glob(dirname(__DIR__) . '/TAXGROK-*.md');
            if (empty($reportFiles)) {
                 echo json_encode(['error' => "Taxgrok failed to generate a report. Output: <br><pre>$output</pre>"]);
                 exit;
            }

            // Read the most recent report (or the one matching the name)
            rsort($reportFiles);
            $reportContent = file_get_contents($reportFiles[0]);

            // Return raw markdown for the frontend to render with marked.js
            $markdown = $reportContent;

            echo json_encode(['success' => true, 'markdown' => $markdown]);
            exit;

        default:
            echo json_encode(['error' => 'Unknown action']);
            exit;
    }
}
?>
<!DOCTYPE html>
<html lang="en">

<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SolTracker — Solana Wallet Tax Tracker</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link
        href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=DM+Sans:wght@400;500;600;700&display=swap"
        rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js"></script>
    <style>
        :root {
            --bg-primary: #0a0a0f;
            --bg-secondary: #12121a;
            --bg-tertiary: #1a1a28;
            --bg-hover: #22223a;
            --bg-active: #2a2a45;
            --border: #2a2a40;
            --border-light: #3a3a55;
            --text-primary: #e8e8f0;
            --text-secondary: #9898b0;
            --text-muted: #606078;
            --accent: #7c5cfc;
            --accent-hover: #9478ff;
            --accent-dim: rgba(124, 92, 252, 0.15);
            --green: #34d399;
            --green-dim: rgba(52, 211, 153, 0.12);
            --red: #f87171;
            --red-dim: rgba(248, 113, 113, 0.12);
            --yellow: #fbbf24;
            --yellow-dim: rgba(251, 191, 36, 0.12);
            --blue: #60a5fa;
            --blue-dim: rgba(96, 165, 250, 0.12);
            --font-mono: 'JetBrains Mono', monospace;
            --font-sans: 'DM Sans', sans-serif;
            --sidebar-width: 300px;
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: var(--font-sans);
            background: var(--bg-primary);
            color: var(--text-primary);
            height: 100vh;
            overflow: hidden;
            display: flex;
        }

        /* --- SIDEBAR --- */
        .sidebar {
            width: var(--sidebar-width);
            min-width: var(--sidebar-width);
            background: var(--bg-secondary);
            border-right: 1px solid var(--border);
            display: flex;
            flex-direction: column;
            height: 100vh;
        }

        .sidebar-header {
            padding: 20px 16px;
            border-bottom: 1px solid var(--border);
        }

        .sidebar-header h1 {
            font-family: var(--font-mono);
            font-size: 18px;
            font-weight: 700;
            letter-spacing: -0.5px;
            margin-bottom: 4px;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .sidebar-header h1 .dot {
            width: 8px;
            height: 8px;
            background: var(--accent);
            border-radius: 50%;
            display: inline-block;
            box-shadow: 0 0 8px var(--accent);
        }

        .sidebar-header p {
            font-size: 12px;
            color: var(--text-muted);
        }

        .sidebar-nav {
            padding: 12px 8px;
            border-bottom: 1px solid var(--border);
            display: flex;
            flex-direction: column;
            gap: 4px;
        }

        .nav-item {
            padding: 10px 12px;
            border-radius: 8px;
            cursor: pointer;
            color: var(--text-secondary);
            font-weight: 600;
            font-size: 14px;
            display: flex;
            align-items: center;
            gap: 8px;
            transition: all 0.2s;
        }

        .nav-item:hover {
            background: var(--bg-hover);
            color: var(--text-primary);
        }

        .nav-item.active {
            background: var(--accent-dim);
            color: var(--accent);
        }

        .solana-tracker-section {
            display: flex;
            flex-direction: column;
            flex: 1;
            overflow: hidden;
        }

        .add-wallet-form {
            padding: 12px 16px;
            border-bottom: 1px solid var(--border);
        }

        .add-wallet-form input {
            width: 100%;
            padding: 10px 12px;
            background: var(--bg-tertiary);
            border: 1px solid var(--border);
            border-radius: 8px;
            color: var(--text-primary);
            font-family: var(--font-mono);
            font-size: 12px;
            outline: none;
            transition: border-color 0.2s;
            margin-bottom: 8px;
        }

        .add-wallet-form input:focus {
            border-color: var(--accent);
        }

        .add-wallet-form input::placeholder {
            color: var(--text-muted);
        }

        .add-wallet-form .form-row {
            display: flex;
            gap: 8px;
        }

        .add-wallet-form .form-row input {
            margin-bottom: 0;
        }

        .btn {
            padding: 10px 16px;
            background: var(--accent);
            color: white;
            border: none;
            border-radius: 8px;
            font-family: var(--font-sans);
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            white-space: nowrap;
        }

        .btn:hover {
            background: var(--accent-hover);
            transform: translateY(-1px);
        }

        .btn:active {
            transform: translateY(0);
        }

        .btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
            transform: none;
        }

        .btn-sm {
            padding: 6px 12px;
            font-size: 12px;
        }

        .btn-outline {
            background: transparent;
            border: 1px solid var(--border);
            color: var(--text-secondary);
        }

        .btn-outline:hover {
            border-color: var(--accent);
            color: var(--accent);
            background: var(--accent-dim);
        }

        .btn-danger {
            background: var(--red-dim);
            color: var(--red);
            border: 1px solid transparent;
        }

        .btn-danger:hover {
            border-color: var(--red);
            background: rgba(248, 113, 113, 0.2);
        }

        .wallet-list {
            flex: 1;
            overflow-y: auto;
            padding: 8px;
        }

        .wallet-list::-webkit-scrollbar {
            width: 4px;
        }

        .wallet-list::-webkit-scrollbar-track {
            background: transparent;
        }

        .wallet-list::-webkit-scrollbar-thumb {
            background: var(--border);
            border-radius: 4px;
        }

        .wallet-item {
            padding: 12px;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.15s;
            margin-bottom: 4px;
            position: relative;
        }

        .wallet-item:hover {
            background: var(--bg-hover);
        }

        .wallet-item.active {
            background: var(--bg-active);
            border-left: 3px solid var(--accent);
        }

        .wallet-item .wallet-label {
            font-weight: 600;
            font-size: 14px;
            margin-bottom: 4px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .wallet-item .wallet-address {
            font-family: var(--font-mono);
            font-size: 11px;
            color: var(--text-muted);
            word-break: break-all;
        }

        .wallet-item .wallet-meta {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-top: 6px;
            font-size: 11px;
            color: var(--text-muted);
        }

        .wallet-item .tx-badge {
            font-family: var(--font-mono);
            font-size: 10px;
            padding: 2px 6px;
            background: var(--accent-dim);
            color: var(--accent);
            border-radius: 4px;
        }

        .wallet-item .delete-btn {
            position: absolute;
            top: 8px;
            right: 8px;
            width: 24px;
            height: 24px;
            background: transparent;
            border: none;
            color: var(--text-muted);
            cursor: pointer;
            border-radius: 4px;
            display: none;
            align-items: center;
            justify-content: center;
            font-size: 14px;
            transition: all 0.15s;
        }

        .wallet-item:hover .delete-btn {
            display: flex;
        }

        .wallet-item .delete-btn:hover {
            background: var(--red-dim);
            color: var(--red);
        }

        .no-wallets {
            padding: 40px 20px;
            text-align: center;
            color: var(--text-muted);
            font-size: 13px;
            line-height: 1.6;
        }

        .no-wallets .icon {
            font-size: 32px;
            margin-bottom: 12px;
            opacity: 0.5;
        }

        /* --- MAIN PANEL --- */
        .main {
            flex: 1;
            display: flex;
            flex-direction: column;
            height: 100vh;
            overflow: hidden;
        }

        .main-header {
            padding: 16px 24px;
            border-bottom: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: var(--bg-secondary);
            min-height: 65px;
        }

        .main-header .wallet-info h2 {
            font-size: 16px;
            font-weight: 600;
            margin-bottom: 2px;
        }

        .main-header .wallet-info .addr {
            font-family: var(--font-mono);
            font-size: 12px;
            color: var(--text-muted);
        }

        .main-header .actions {
            display: flex;
            gap: 8px;
            align-items: center;
        }

        .toolbar {
            padding: 12px 24px;
            border-bottom: 1px solid var(--border);
            display: flex;
            gap: 12px;
            align-items: center;
            background: var(--bg-primary);
            flex-wrap: wrap;
        }

        .toolbar select {
            padding: 8px 12px;
            background: var(--bg-tertiary);
            border: 1px solid var(--border);
            border-radius: 6px;
            color: var(--text-primary);
            font-family: var(--font-sans);
            font-size: 13px;
            outline: none;
            cursor: pointer;
        }

        .toolbar select:focus {
            border-color: var(--accent);
        }

        .toolbar input[type="text"] {
            padding: 8px 12px;
            background: var(--bg-tertiary);
            border: 1px solid var(--border);
            border-radius: 6px;
            color: var(--text-primary);
            font-family: var(--font-mono);
            font-size: 12px;
            outline: none;
            width: 260px;
        }

        .toolbar input[type="text"]:focus {
            border-color: var(--accent);
        }

        .toolbar .tx-count {
            font-family: var(--font-mono);
            font-size: 12px;
            color: var(--text-muted);
            margin-left: auto;
        }

        .tx-table-wrap {
            flex: 1;
            overflow-y: auto;
            padding: 0;
        }

        .tx-table-wrap::-webkit-scrollbar {
            width: 6px;
        }

        .tx-table-wrap::-webkit-scrollbar-track {
            background: transparent;
        }

        .tx-table-wrap::-webkit-scrollbar-thumb {
            background: var(--border);
            border-radius: 4px;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }

        thead {
            position: sticky;
            top: 0;
            z-index: 10;
            background: var(--bg-secondary);
        }

        th {
            padding: 10px 16px;
            text-align: left;
            font-weight: 600;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--text-muted);
            border-bottom: 1px solid var(--border);
            white-space: nowrap;
        }

        td {
            padding: 10px 16px;
            border-bottom: 1px solid var(--border);
            vertical-align: middle;
        }

        tr:hover td {
            background: var(--bg-hover);
        }

        .type-badge {
            font-family: var(--font-mono);
            font-size: 10px;
            font-weight: 600;
            padding: 3px 8px;
            border-radius: 4px;
            text-transform: uppercase;
            letter-spacing: 0.3px;
            white-space: nowrap;
        }

        .type-TRANSFER {
            background: var(--blue-dim);
            color: var(--blue);
        }

        .type-SWAP {
            background: var(--green-dim);
            color: var(--green);
        }

        .type-NFT {
            background: var(--yellow-dim);
            color: var(--yellow);
        }

        .type-UNKNOWN {
            background: var(--bg-tertiary);
            color: var(--text-muted);
        }

        .type-COMPRESSED_NFT_MINT,
        .type-NFT_MINT {
            background: var(--yellow-dim);
            color: var(--yellow);
        }

        .type-NFT_SALE,
        .type-NFT_LISTING {
            background: var(--yellow-dim);
            color: var(--yellow);
        }

        .type-BURN {
            background: var(--red-dim);
            color: var(--red);
        }

        .type-default {
            background: var(--accent-dim);
            color: var(--accent);
        }

        .mono {
            font-family: var(--font-mono);
            font-size: 11px;
        }

        .muted {
            color: var(--text-muted);
        }

        .truncate {
            max-width: 120px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .amt-positive {
            color: var(--green);
        }

        .amt-negative {
            color: var(--red);
        }

        .sig-link {
            color: var(--accent);
            text-decoration: none;
            font-family: var(--font-mono);
            font-size: 11px;
        }

        .sig-link:hover {
            color: var(--accent-hover);
            text-decoration: underline;
        }

        .desc-cell {
            max-width: 300px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            font-size: 12px;
            color: var(--text-secondary);
        }

        .pagination {
            padding: 12px 24px;
            border-top: 1px solid var(--border);
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 8px;
            background: var(--bg-secondary);
        }

        .pagination .page-info {
            font-family: var(--font-mono);
            font-size: 12px;
            color: var(--text-muted);
            margin: 0 12px;
        }

        /* --- EMPTY STATE --- */
        .empty-main {
            flex: 1;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            color: var(--text-muted);
            padding: 40px;
            text-align: center;
        }

        .empty-main .big-icon {
            font-size: 48px;
            margin-bottom: 16px;
            opacity: 0.3;
        }

        .empty-main h3 {
            font-size: 18px;
            color: var(--text-secondary);
            margin-bottom: 8px;
        }

        .empty-main p {
            font-size: 14px;
            max-width: 400px;
            line-height: 1.6;
        }

        /* --- LOADING SPINNER --- */
        .spinner {
            width: 16px;
            height: 16px;
            border: 2px solid var(--border);
            border-top-color: var(--accent);
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
            display: inline-block;
        }

        @keyframes spin {
            to {
                transform: rotate(360deg);
            }
        }

        .syncing-overlay {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0, 0, 0, 0.5);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 100;
            backdrop-filter: blur(4px);
        }

        .syncing-card {
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 32px 40px;
            text-align: center;
        }

        .syncing-card .spinner {
            width: 32px;
            height: 32px;
            border-width: 3px;
            margin-bottom: 16px;
        }

        .syncing-card h3 {
            margin-bottom: 6px;
            font-size: 16px;
        }

        .syncing-card p {
            color: var(--text-muted);
            font-size: 13px;
        }

        /* --- TOAST --- */
        .toast {
            position: fixed;
            bottom: 24px;
            right: 24px;
            padding: 12px 20px;
            background: var(--bg-tertiary);
            border: 1px solid var(--border);
            border-radius: 8px;
            color: var(--text-primary);
            font-size: 13px;
            z-index: 200;
            opacity: 0;
            transform: translateY(10px);
            transition: all 0.3s;
            pointer-events: none;
        }

        .toast.show {
            opacity: 1;
            transform: translateY(0);
            pointer-events: auto;
        }

        .toast.error {
            border-color: var(--red);
            background: var(--red-dim);
        }

        .toast.success {
            border-color: var(--green);
            background: var(--green-dim);
        }

        /* --- API KEY WARNING --- */
        .api-warning {
            background: var(--yellow-dim);
            border: 1px solid rgba(251, 191, 36, 0.3);
            border-radius: 8px;
            padding: 16px 20px;
            margin: 16px;
            font-size: 13px;
            color: var(--yellow);
            line-height: 1.5;
        }

        .api-warning a {
            color: var(--yellow);
            font-weight: 600;
        }

        /* --- TAXGROK DASHBOARD --- */
        .taxgrok-dashboard {
            flex: 1;
            display: flex;
            flex-direction: column;
            overflow-y: auto;
            background: var(--bg-primary);
            padding: 32px 48px;
        }

        .taxgrok-dashboard h2 {
            font-size: 28px;
            margin-bottom: 8px;
            font-family: var(--font-mono);
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .taxgrok-dashboard p.subtitle {
            color: var(--text-secondary);
            font-size: 15px;
            margin-bottom: 32px;
        }

        .upload-card {
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 24px;
            max-width: 600px;
        }

        .form-group {
            margin-bottom: 20px;
        }

        .form-group label {
            display: block;
            margin-bottom: 8px;
            font-weight: 600;
            font-size: 13px;
            color: var(--text-secondary);
        }

        .taxgrok-input {
            width: 100%;
            padding: 12px 16px;
            background: var(--bg-tertiary);
            border: 1px solid var(--border);
            border-radius: 8px;
            color: var(--text-primary);
            font-size: 14px;
            outline: none;
            transition: border-color 0.2s;
        }

        .taxgrok-input:focus {
            border-color: var(--accent);
        }

        .file-upload-box {
            border: 2px dashed var(--border);
            border-radius: 8px;
            padding: 32px;
            text-align: center;
            background: var(--bg-tertiary);
            cursor: pointer;
            transition: all 0.2s;
            margin-bottom: 20px;
        }

        .file-upload-box:hover {
            border-color: var(--accent);
            background: var(--bg-hover);
        }

        .file-upload-box p {
            color: var(--text-muted);
            font-size: 14px;
            margin-top: 8px;
        }

        .file-upload-box .icon {
            font-size: 32px;
            color: var(--text-secondary);
        }

        input[type="file"] {
            display: none;
        }

        .taxgrok-result {
            margin-top: 32px;
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 40px;
            display: none;
            line-height: 1.7;
            color: var(--text-primary);
        }

        .taxgrok-result-content h1, 
        .taxgrok-result-content h2, 
        .taxgrok-result-content h3 {
            margin-top: 32px;
            margin-bottom: 16px;
            font-family: var(--font-mono);
            color: var(--text-primary);
            border-bottom: 1px solid var(--border-light);
            padding-bottom: 8px;
        }

        .taxgrok-result-content h1 { font-size: 24px; color: var(--accent); border-bottom-color: var(--accent-dim); }
        .taxgrok-result-content h2 { font-size: 20px; }
        .taxgrok-result-content h3 { font-size: 16px; color: var(--text-secondary); border: none; padding-bottom: 0; }

        .taxgrok-result-content p {
            margin-bottom: 20px;
            color: var(--text-secondary);
            font-size: 15px;
        }

        .taxgrok-result-content strong {
            color: var(--text-primary);
            font-weight: 600;
        }

        .taxgrok-result-content ul, 
        .taxgrok-result-content ol {
            margin-bottom: 24px;
            padding-left: 28px;
            color: var(--text-secondary);
            font-size: 15px;
        }

        .taxgrok-result-content li {
            margin-bottom: 10px;
        }
        
        .taxgrok-result-content li::marker {
            color: var(--accent);
        }

        .taxgrok-result-content blockquote {
            border-left: 4px solid var(--accent);
            padding-left: 16px;
            margin: 24px 0;
            color: var(--text-muted);
            background: var(--bg-tertiary);
            padding: 16px;
            border-radius: 0 8px 8px 0;
            font-style: italic;
        }

        .taxgrok-result-content code {
            font-family: var(--font-mono);
            background: var(--bg-tertiary);
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 13px;
            color: var(--accent-hover);
            border: 1px solid var(--border);
        }

        .taxgrok-result-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 24px;
            padding-bottom: 16px;
            border-bottom: 1px dashed var(--border);
        }

        .taxgrok-result-header h3 {
            margin: 0;
            font-family: var(--font-mono);
            color: var(--text-primary);
        }
        
        /* PDF specific styling overrides */
        .pdf-export-mode {
            background: white !important;
            color: black !important;
        }
        
        .pdf-export-mode .taxgrok-result-content h1,
        .pdf-export-mode .taxgrok-result-content h2,
        .pdf-export-mode .taxgrok-result-content h3,
        .pdf-export-mode .taxgrok-result-content p,
        .pdf-export-mode .taxgrok-result-content strong,
        .pdf-export-mode .taxgrok-result-content ul,
        .pdf-export-mode .taxgrok-result-content ol,
        .pdf-export-mode .taxgrok-result-content code,
        .pdf-export-mode .taxgrok-result-content pre {
            color: black !important;
        }
        
        .pdf-export-mode .taxgrok-result-content code,
        .pdf-export-mode .taxgrok-result-content pre {
            background: transparent !important;
            border-color: black !important;
        }
        
        .pdf-export-mode .taxgrok-result-content h1 { border-bottom-color: #e5e7eb !important; color: #4338ca !important; }
        .pdf-export-mode .taxgrok-result-content h2 { border-bottom-color: #e5e7eb !important; }
        .pdf-export-mode .taxgrok-result-content blockquote { background: #f3f4f6 !important; border-left-color: #4338ca !important;}
        .pdf-export-mode .taxgrok-result-header { border-bottom-color: #e5e7eb !important; }

        /* --- RESPONSIVE --- */
        @media (max-width: 768px) {
            .sidebar {
                width: 260px;
                min-width: 260px;
            }

            .toolbar input[type="text"] {
                width: 160px;
            }
        }
    </style>
</head>

<body>

    <!-- SIDEBAR -->
    <aside class="sidebar">
        <div class="sidebar-header">
            <h1><span class="dot"></span> Taxgrok</h1>
            <p>The AI Tax Prep Assistant</p>
        </div>

        <div class="sidebar-nav">
            <div class="nav-item active" id="nav-taxgrok" onclick="switchTab('taxgrok')">
                🧠 Dashboard
            </div>
            <div class="nav-item" id="nav-solana" onclick="switchTab('solana')">
                ◎ Solana Tracker
            </div>
        </div>

        <div id="solana-tracker-sidebar" class="solana-tracker-section" style="display: none;">
            <?php if (empty(HELIUS_API_KEY)): ?>
                <div class="api-warning">
                    ⚠️ No API key configured.<br>
                    Get a free key at <a href="https://helius.dev" target="_blank">helius.dev</a>, then paste it in the
                    <code>HELIUS_API_KEY</code> constant at the top of this file.
                </div>
            <?php endif; ?>

            <div class="add-wallet-form">
                <label for="walletAddress" style="display:none">Wallet Address</label>
                <input type="text" id="walletAddress" name="walletAddress" placeholder="Enter Solana wallet address..." maxlength="44"
                    spellcheck="false">
                <div class="form-row">
                    <label for="walletLabel" style="display:none">Wallet Label</label>
                    <input type="text" id="walletLabel" name="walletLabel" placeholder="Label (optional)" maxlength="32">
                    <button class="btn btn-sm" onclick="addWallet()">+ Add</button>
                </div>
            </div>

            <div class="wallet-list" id="walletList">
                <div class="no-wallets" id="noWallets">
                    <div class="icon">◎</div>
                    Add a Solana wallet address<br>to start tracking transactions
                </div>
            </div>
        </div>
    </aside>

    <!-- MAIN PANEL -->
    
    <!-- Taxgrok Dashboard -->
    <main class="taxgrok-dashboard" id="taxgrokPanel">
        <h2>🧠 Taxgrok Dashboard</h2>
        <p class="subtitle">AI-powered tax preparation briefing from your documents.</p>

        <div class="upload-card">
            <form id="taxgrokForm" onsubmit="runTaxgrok(event)">
                <div class="form-group">
                    <label for="taxpayerName">Taxpayer Name</label>
                    <input type="text" id="taxpayerName" name="taxpayerName" class="taxgrok-input" required placeholder="e.g. John Doe">
                </div>
                
                <div class="form-group">
                    <label for="filingStatus">Filing Status</label>
                    <select id="filingStatus" name="filingStatus" class="taxgrok-input" required>
                        <option value="Single">Single</option>
                        <option value="Married Filing Jointly">Married Filing Jointly</option>
                        <option value="Married Filing Separately">Married Filing Separately</option>
                        <option value="Head of Household">Head of Household</option>
                        <option value="Qualifying Surviving Spouse">Qualifying Surviving Spouse</option>
                        <option value="Not Sure">Not Sure</option>
                    </select>
                </div>

                <div class="form-group">
                    <label for="xaiApiKey">XAI API Key <span style="font-weight:normal; color:var(--text-muted);">(Get one at <a href="https://console.x.ai" target="_blank" style="color:var(--accent);">console.x.ai</a>)</span></label>
                    <input type="password" id="xaiApiKey" name="xaiApiKey" class="taxgrok-input" required placeholder="xai-...">
                </div>

                <div class="form-group">
                    <label for="taxDocs">Tax Documents (.txt, .md, .pdf, .png)</label>
                    <div class="file-upload-box" onclick="document.getElementById('taxDocs').click()">
                        <div class="icon">📄</div>
                        <p id="fileUploadText">Click to select files or drag & drop</p>
                    </div>
                    <input type="file" id="taxDocs" name="taxDocs" multiple accept=".txt,.md,.pdf,.png" onchange="updateFileText()">
                </div>

                <button type="submit" class="btn" style="width: 100%; font-size: 15px; padding: 14px;" id="runTaxgrokBtn">Generate Tax Briefing</button>
            </form>
        </div>

        <div class="taxgrok-result" id="taxgrokResult">
            <div class="taxgrok-result-header" id="taxgrokResultHeader">
                <h3>Tax Briefing Report</h3>
                <button class="btn btn-sm btn-outline" onclick="exportTaxgrokPDF()" style="display: flex; align-items: center; gap: 6px;">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
                    Export PDF
                </button>
            </div>
            <div class="taxgrok-result-content" id="taxgrokResultContent">
                <!-- Markdown Output rendered here -->
            </div>
        </div>
    </main>

    <!-- Solana Tracker Main Panel -->
    <main class="main" id="mainPanel" style="display: none;">
        <div class="empty-main" id="emptyState">
            <div class="big-icon">◎</div>
            <h3>No wallet selected</h3>
            <p>Add a wallet address in the sidebar, then click it to view transactions. Hit sync to pull the latest data
                from the blockchain.</p>
        </div>
    </main>

    <!-- SYNCING OVERLAY -->
    <div class="syncing-overlay" id="syncOverlay" style="display:none">
        <div class="syncing-card">
            <div class="spinner"></div>
            <h3>Syncing Wallet</h3>
            <p id="syncStatus">Fetching transactions from Helius...</p>
        </div>
    </div>

    <!-- TOAST -->
    <div class="toast" id="toast"></div>

    <script>
        // --- STATE ---
        let wallets = [];
        let activeWalletId = null;
        let currentPage = 1;
        let currentType = 'ALL';
        let currentSearch = '';
        let txTypes = [];

        // --- NAVIGATION ---
        function switchTab(tab) {
            if (tab === 'taxgrok') {
                document.getElementById('nav-taxgrok').classList.add('active');
                document.getElementById('nav-solana').classList.remove('active');
                document.getElementById('taxgrokPanel').style.display = 'flex';
                document.getElementById('mainPanel').style.display = 'none';
                document.getElementById('solana-tracker-sidebar').style.display = 'none';
            } else if (tab === 'solana') {
                document.getElementById('nav-solana').classList.add('active');
                document.getElementById('nav-taxgrok').classList.remove('active');
                document.getElementById('solana-tracker-sidebar').style.display = 'flex';
                document.getElementById('mainPanel').style.display = 'flex';
                document.getElementById('taxgrokPanel').style.display = 'none';
            }
        }

        // --- HELPERS ---
        async function api(action, data = {}, method = 'POST') {
            const opts = { method };
            if (method === 'POST') {
                const fd = new FormData();
                fd.append('action', action);
                for (const [k, v] of Object.entries(data)) fd.append(k, v);
                opts.body = fd;
            }
            const url = method === 'GET'
                ? `?action=${action}&${new URLSearchParams(data)}`
                : `?action=${action}`;

            // for GET, we actually need the params in the URL  
            const finalUrl = method === 'GET' ? `?${new URLSearchParams({ action, ...data })}` : '?';
            const response = await fetch(method === 'GET' ? finalUrl : '?', opts);
            return response.json();
        }

        function toast(msg, type = '') {
            const t = document.getElementById('toast');
            t.textContent = msg;
            t.className = 'toast show ' + type;
            setTimeout(() => t.className = 'toast', 3000);
        }

        function truncateAddr(addr, chars = 6) {
            if (!addr || addr.length <= chars * 2) return addr || '';
            return addr.slice(0, chars) + '...' + addr.slice(-chars);
        }

        function formatDate(ts) {
            const d = new Date(ts * 1000);
            return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
        }

        function formatTime(ts) {
            const d = new Date(ts * 1000);
            return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: true });
        }

        function formatAmount(amt) {
            if (!amt || amt === 0) return '—';
            const num = parseFloat(amt);
            if (Math.abs(num) < 0.001) return num.toExponential(2);
            if (Math.abs(num) < 1) return num.toFixed(6);
            if (Math.abs(num) < 1000) return num.toFixed(4);
            return num.toLocaleString('en-US', { maximumFractionDigits: 2 });
        }

        function getTypeBadgeClass(type) {
            const known = ['TRANSFER', 'SWAP', 'NFT', 'UNKNOWN', 'BURN', 'COMPRESSED_NFT_MINT', 'NFT_MINT', 'NFT_SALE', 'NFT_LISTING'];
            return known.includes(type) ? `type-${type}` : 'type-default';
        }

        // --- WALLET OPERATIONS ---
        async function loadWallets() {
            wallets = await api('list_wallets', {}, 'GET');
            renderWallets();
        }

        function renderWallets() {
            const list = document.getElementById('walletList');

            if (!wallets.length) {
                list.innerHTML = `
                <div class="no-wallets" id="noWallets">
                    <div class="icon">◎</div>
                    Add a Solana wallet address<br>to start tracking transactions
                </div>`;
                return;
            }

            list.innerHTML = wallets.map(w => `
        <div class="wallet-item ${w.id == activeWalletId ? 'active' : ''}" onclick="selectWallet(${w.id})">
            <button class="delete-btn" onclick="event.stopPropagation(); deleteWallet(${w.id}, '${escapeHtml(w.label)}')" title="Delete wallet">×</button>
            <div class="wallet-label">
                ${escapeHtml(w.label)}
                ${w.tx_count > 0 ? `<span class="tx-badge">${w.tx_count} tx</span>` : ''}
            </div>
            <div class="wallet-address">${w.address}</div>
            <div class="wallet-meta">
                <span>${w.last_synced ? 'Synced: ' + new Date(w.last_synced + 'Z').toLocaleDateString() : 'Not synced'}</span>
            </div>
        </div>
    `).join('');
        }

        function escapeHtml(str) {
            const div = document.createElement('div');
            div.textContent = str;
            return div.innerHTML;
        }

        async function addWallet() {
            const addr = document.getElementById('walletAddress').value.trim();
            const label = document.getElementById('walletLabel').value.trim();

            if (!addr) { toast('Enter a wallet address', 'error'); return; }

            const result = await api('add_wallet', { address: addr, label: label });
            if (result.error) { toast(result.error, 'error'); return; }

            document.getElementById('walletAddress').value = '';
            document.getElementById('walletLabel').value = '';
            toast('Wallet added!', 'success');
            await loadWallets();
            selectWallet(result.wallet.id);
        }

        async function deleteWallet(id, label) {
            if (!confirm(`Delete wallet "${label}" and all its transactions?`)) return;
            await api('delete_wallet', { id });
            if (activeWalletId === id) {
                activeWalletId = null;
                showEmptyState();
            }
            toast('Wallet deleted', 'success');
            await loadWallets();
        }

        async function selectWallet(id) {
            activeWalletId = id;
            currentPage = 1;
            currentType = 'ALL';
            currentSearch = '';
            renderWallets();
            
            // Switch tab to solana automatically if not already
            switchTab('solana');
            
            await loadTransactions();
        }

        // --- TRANSACTION OPERATIONS ---
        async function syncActiveWallet() {
            if (!activeWalletId) return;

            document.getElementById('syncOverlay').style.display = 'flex';
            document.getElementById('syncStatus').textContent = 'Fetching transactions from Helius...';

            try {
                const result = await api('sync_wallet', { id: activeWalletId });
                document.getElementById('syncOverlay').style.display = 'none';

                if (result.error) {
                    toast(result.error, 'error');
                    return;
                }

                toast(`Synced! ${result.new_transactions} new transactions found.`, 'success');
                await loadWallets();
                await loadTransactions();
            } catch (e) {
                document.getElementById('syncOverlay').style.display = 'none';
                toast('Sync failed: ' + e.message, 'error');
            }
        }

        async function loadTransactions() {
            if (!activeWalletId) return;

            const wallet = wallets.find(w => w.id == activeWalletId);
            if (!wallet) return;

            const result = await api('list_transactions', {
                wallet_id: activeWalletId,
                page: currentPage,
                type: currentType,
                search: currentSearch
            }, 'GET');

            txTypes = result.types || [];
            renderMainPanel(wallet, result);
        }

        function renderMainPanel(wallet, data) {
            const main = document.getElementById('mainPanel');
            const { transactions, total, page, pages, types } = data;

            let typeOptions = '<option value="ALL">All Types</option>' +
                types.map(t => `<option value="${t}" ${t === currentType ? 'selected' : ''}>${t}</option>`).join('');

            let txRows = '';
            if (transactions.length === 0) {
                txRows = `<tr><td colspan="8" style="text-align:center; padding:40px; color:var(--text-muted);">
            ${wallet.tx_count === 0 ? 'No transactions yet. Click <strong>Sync</strong> to fetch from the blockchain.' : 'No transactions match your filters.'}
        </td></tr>`;
            } else {
                txRows = transactions.map(tx => {
                    const isReceive = tx.to_address && tx.to_address.toLowerCase() === wallet.address.toLowerCase();
                    const amtClass = isReceive ? 'amt-positive' : '';
                    const amtPrefix = isReceive ? '+' : '';

                    return `<tr>
                <td class="mono muted">${formatDate(tx.timestamp)}<br>${formatTime(tx.timestamp)}</td>
                <td><span class="type-badge ${getTypeBadgeClass(tx.type)}">${tx.type}</span></td>
                <td class="desc-cell" title="${escapeHtml(tx.description)}">${escapeHtml(tx.description || '—')}</td>
                <td class="mono truncate" title="${tx.from_address}">${truncateAddr(tx.from_address, 4)}</td>
                <td class="mono truncate" title="${tx.to_address}">${truncateAddr(tx.to_address, 4)}</td>
                <td class="mono ${amtClass}" style="white-space:nowrap">${amtPrefix}${formatAmount(tx.amount)} <span class="muted">${escapeHtml(tx.token_symbol)}</span></td>
                <td class="mono muted">${tx.fee_sol ? tx.fee_sol.toFixed(6) : '—'}</td>
                <td><a class="sig-link" href="https://solscan.io/tx/${tx.signature}" target="_blank" title="${tx.signature}">${truncateAddr(tx.signature, 4)}</a></td>
            </tr>`;
                }).join('');
            }

            let paginationHtml = '';
            if (pages > 1) {
                paginationHtml = `
        <div class="pagination">
            <button class="btn btn-sm btn-outline" onclick="changePage(${page - 1})" ${page <= 1 ? 'disabled' : ''}>← Prev</button>
            <span class="page-info">Page ${page} of ${pages}</span>
            <button class="btn btn-sm btn-outline" onclick="changePage(${page + 1})" ${page >= pages ? 'disabled' : ''}>Next →</button>
        </div>`;
            }

            const netSolClass = data.summary.net_sol >= 0 ? 'amt-positive' : 'amt-negative';
            const netSolPrefix = data.summary.net_sol >= 0 ? '+' : '';

            main.innerHTML = `
        <div class="main-header">
            <div class="wallet-info">
                <h2>${escapeHtml(wallet.label)}</h2>
                <div class="addr">${wallet.address}</div>
            </div>
            <div class="actions">
                <button class="btn btn-sm btn-outline" onclick="exportCSV()">⬇ Export CSV</button>
                <button class="btn btn-sm" onclick="syncActiveWallet()">↻ Sync</button>
            </div>
        </div>
        
        <div class="summary-cards" style="display:flex; gap:16px; margin-bottom:24px; padding: 0 40px;">
            <div class="summary-card" style="flex:1; background:var(--bg-tertiary); padding:20px; border-radius:12px; border:1px solid var(--border);">
                <div style="font-size:13px; color:var(--text-secondary); margin-bottom:8px; font-weight:600;">Total SOL In</div>
                <div style="font-size:24px; font-family:var(--font-mono); color:var(--green)">+${formatAmount(data.summary.sol_in)}</div>
            </div>
            <div class="summary-card" style="flex:1; background:var(--bg-tertiary); padding:20px; border-radius:12px; border:1px solid var(--border);">
                <div style="font-size:13px; color:var(--text-secondary); margin-bottom:8px; font-weight:600;">Total SOL Out</div>
                <div style="font-size:24px; font-family:var(--font-mono); color:var(--text-primary)">-${formatAmount(data.summary.sol_out)}</div>
            </div>
            <div class="summary-card" style="flex:1; background:var(--bg-tertiary); padding:20px; border-radius:12px; border:1px solid var(--border);">
                <div style="font-size:13px; color:var(--text-secondary); margin-bottom:8px; font-weight:600;">Net SOL</div>
                <div style="font-size:24px; font-family:var(--font-mono); color:var(--${data.summary.net_sol >= 0 ? 'green' : 'text-primary'})">${netSolPrefix}${formatAmount(data.summary.net_sol)}</div>
            </div>
            <div class="summary-card" style="flex:1; background:var(--bg-tertiary); padding:20px; border-radius:12px; border:1px solid var(--border);">
                <div style="font-size:13px; color:var(--text-secondary); margin-bottom:8px; font-weight:600;">Total Fees Paid</div>
                <div style="font-size:24px; font-family:var(--font-mono); color:var(--yellow)">${formatAmount(data.summary.total_fees)}</div>
            </div>
        </div>

        <div class="toolbar">
            <select onchange="filterType(this.value)">${typeOptions}</select>
            <input type="text" placeholder="Search signatures, addresses, tokens..." 
                   value="${escapeHtml(currentSearch)}" 
                   oninput="debounceSearch(this.value)">
            <span class="tx-count">${total} transaction${total !== 1 ? 's' : ''}</span>
        </div>
        <div class="tx-table-wrap">
            <table>
                <thead>
                    <tr>
                        <th>Date</th>
                        <th>Type</th>
                        <th>Description</th>
                        <th>From</th>
                        <th>To</th>
                        <th>Amount</th>
                        <th>Fee</th>
                        <th>Signature</th>
                    </tr>
                </thead>
                <tbody>${txRows}</tbody>
            </table>
        </div>
        ${paginationHtml}
    `;
        }

        function showEmptyState() {
            document.getElementById('mainPanel').innerHTML = `
        <div class="empty-main" id="emptyState">
            <div class="big-icon">◎</div>
            <h3>No wallet selected</h3>
            <p>Add a wallet address in the sidebar, then click it to view transactions. Hit sync to pull the latest data from the blockchain.</p>
        </div>
    `;
        }

        // --- FILTERS ---
        function filterType(type) {
            currentType = type;
            currentPage = 1;
            loadTransactions();
        }

        let searchTimeout;
        function debounceSearch(value) {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                currentSearch = value;
                currentPage = 1;
                loadTransactions();
            }, 300);
        }

        function changePage(p) {
            currentPage = p;
            loadTransactions();
        }

        function exportCSV() {
            if (!activeWalletId) return;
            window.open(`?action=export_csv&wallet_id=${activeWalletId}`, '_blank');
        }

        // --- TAXGROK LOGIC ---
        function updateFileText() {
            const input = document.getElementById('taxDocs');
            const txt = document.getElementById('fileUploadText');
            if (input.files && input.files.length > 0) {
                txt.textContent = `${input.files.length} file(s) selected`;
                txt.style.color = 'var(--text-primary)';
            } else {
                txt.textContent = 'Click to select files or drag & drop';
                txt.style.color = 'var(--text-muted)';
            }
        }

        async function runTaxgrok(e) {
            e.preventDefault();
            
            const name = document.getElementById('taxpayerName').value;
            const status = document.getElementById('filingStatus').value;
            const apiKey = document.getElementById('xaiApiKey').value;
            const files = document.getElementById('taxDocs').files;
            
            const btn = document.getElementById('runTaxgrokBtn');
            const resultDiv = document.getElementById('taxgrokResult');
            
            if (files.length === 0) {
                toast('Please select at least one document.', 'error');
                return;
            }
            
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner" style="width: 14px; height: 14px; margin-right: 8px; border-width: 2px;"></span> Analyzing...';
            resultDiv.style.display = 'none';
            
            const formData = new FormData();
            formData.append('action', 'run_taxgrok');
            formData.append('taxpayer_name', name);
            formData.append('filing_status', status);
            formData.append('xai_api_key', apiKey);
            
            for (let i = 0; i < files.length; i++) {
                formData.append('documents[]', files[i]);
            }
            
            try {
                const response = await fetch('?', {
                    method: 'POST',
                    body: formData
                });
                
                const data = await response.json();
                
                if (data.error) {
                    toast(data.error, 'error');
                } else if (data.success && data.markdown) {
                    toast('Generation complete!', 'success');
                    
                    // Parse markdown to HTML using marked.js
                    document.getElementById('taxgrokResultContent').innerHTML = marked.parse(data.markdown);
                    resultDiv.style.display = 'block';
                    
                    // Scroll to result slightly below the top to see the header
                    resultDiv.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }
            } catch (err) {
                toast('Error connecting to backend: ' + err.message, 'error');
            } finally {
                btn.disabled = false;
                btn.textContent = 'Generate Tax Briefing';
            }
        }
        
        async function exportTaxgrokPDF() {
            const element = document.getElementById('taxgrokResult');
            const btn = document.querySelector('#taxgrokResultHeader button');
            
            // visually prepare element for PDF export
            const originalDisplay = btn.style.display;
            btn.style.display = 'none'; // hide export button in PDF
            element.classList.add('pdf-export-mode');
            
            const name = document.getElementById('taxpayerName').value || 'Taxpayer';
            const dateStr = new Date().toISOString().split('T')[0];
            const filename = `Taxgrok_Briefing_${name.replace(/\s+/g, '_')}_${dateStr}.pdf`;
            
            const opt = {
                margin:       15,
                filename:     filename,
                image:        { type: 'jpeg', quality: 0.98 },
                html2canvas:  { scale: 2, useCORS: true },
                jsPDF:        { unit: 'mm', format: 'letter', orientation: 'portrait' }
            };

            toast('Generating PDF...', 'success');
            
            try {
                await html2pdf().set(opt).from(element).save();
                toast('PDF exported successfully!', 'success');
            } catch(e) {
                toast('Error generating PDF: ' + e.message, 'error');
            } finally {
                // restore original styles
                btn.style.display = originalDisplay;
                element.classList.remove('pdf-export-mode');
            }
        }

        // --- KEYBOARD SHORTCUTS ---
        document.getElementById('walletAddress').addEventListener('keydown', e => {
            if (e.key === 'Enter') addWallet();
        });

        document.getElementById('walletLabel').addEventListener('keydown', e => {
            if (e.key === 'Enter') addWallet();
        });

        // --- INIT ---
        loadWallets();
    </script>
</body>

</html>