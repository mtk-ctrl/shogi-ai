package com.mtkctrl.shogiai;

import android.app.Activity;
import android.os.Bundle;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.File;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;

public class MainActivity extends Activity {
    private TextView logView;
    private Button testButton;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setTitle("shogi-ai OEX");

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        int pad = (int) (16 * getResources().getDisplayMetrics().density);
        root.setPadding(pad, pad, pad, pad);

        TextView title = new TextView(this);
        title.setText("shogi-ai v0.0.13\nOEX engine for ShogiDroid2");
        title.setTextSize(20f);
        root.addView(title, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT));

        testButton = new Button(this);
        testButton.setText("USI接続テスト");
        root.addView(testButton, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT));

        ScrollView scroll = new ScrollView(this);
        logView = new TextView(this);
        logView.setText("未テスト\n");
        logView.setTextIsSelectable(true);
        scroll.addView(logView);
        root.addView(scroll, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));

        setContentView(root);

        testButton.setOnClickListener(v -> runUsiTest());
    }

    private void runUsiTest() {
        testButton.setEnabled(false);
        logView.setText("テスト開始...\n");

        new Thread(() -> {
            Process process = null;
            try {
                String enginePath = getApplicationInfo().nativeLibraryDir
                        + File.separator + "libshogiai.so";
                appendLog("engine: " + enginePath);

                ProcessBuilder pb = new ProcessBuilder(enginePath);
                pb.redirectErrorStream(true);
                pb.directory(getFilesDir());
                process = pb.start();

                BufferedWriter writer = new BufferedWriter(
                        new OutputStreamWriter(process.getOutputStream()));
                BufferedReader reader = new BufferedReader(
                        new InputStreamReader(process.getInputStream()));

                send(writer, "usi");
                waitFor(reader, "usiok");

                send(writer, "isready");
                waitFor(reader, "readyok");

                send(writer, "usinewgame");
                send(writer, "position startpos");
                send(writer, "go");
                String bestMove = waitForPrefix(reader, "bestmove ");

                send(writer, "quit");
                appendLog("SUCCESS: " + bestMove);
            } catch (Exception e) {
                appendLog("ERROR: " + e.getClass().getSimpleName() + ": " + e.getMessage());
            } finally {
                if (process != null) {
                    process.destroy();
                }
                runOnUiThread(() -> testButton.setEnabled(true));
            }
        }).start();
    }

    private void send(BufferedWriter writer, String command) throws Exception {
        appendLog("> " + command);
        writer.write(command);
        writer.newLine();
        writer.flush();
    }

    private void waitFor(BufferedReader reader, String expected) throws Exception {
        String line;
        while ((line = reader.readLine()) != null) {
            appendLog("< " + line);
            if (line.trim().equals(expected)) {
                return;
            }
        }
        throw new IllegalStateException("Expected response not received: " + expected);
    }

    private String waitForPrefix(BufferedReader reader, String prefix) throws Exception {
        String line;
        while ((line = reader.readLine()) != null) {
            appendLog("< " + line);
            if (line.startsWith(prefix)) {
                return line;
            }
        }
        throw new IllegalStateException("Expected response not received: " + prefix);
    }

    private void appendLog(String text) {
        runOnUiThread(() -> logView.append(text + "\n"));
    }
}
