package org.beadsshadow.mobile;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.webkit.CookieManager;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

public final class MainActivity extends Activity {
    private static final int PICK_FILE = 41;
    private final Uri origin = Uri.parse(BuildConfig.BEADS_ORIGIN);
    private WebView webView;
    private ValueCallback<Uri[]> fileCallback;

    private static int port(Uri url) {
        if (url.getPort() != -1) {
            return url.getPort();
        }
        return "https".equals(url.getScheme()) ? 443 : 80;
    }

    private boolean sameOrigin(Uri url) {
        return origin.getScheme().equals(url.getScheme())
                && origin.getHost().equalsIgnoreCase(url.getHost())
                && port(origin) == port(url)
                && url.getUserInfo() == null;
    }

    @Override
    public void onCreate(Bundle state) {
        super.onCreate(state);
        webView = new WebView(this);
        setContentView(webView);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setSupportMultipleWindows(false);
        CookieManager.getInstance().setAcceptThirdPartyCookies(webView, false);
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                return !sameOrigin(request.getUrl());
            }
        });
        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                finishFileChooser(null);
                fileCallback = callback;
                try {
                    startActivityForResult(params.createIntent(), PICK_FILE);
                } catch (ActivityNotFoundException exception) {
                    finishFileChooser(null);
                }
                return true;
            }
        });
        webView.setDownloadListener((url, agent, disposition, type, length) ->
                Toast.makeText(this, "请在浏览器中打开豆影以下载图纸", Toast.LENGTH_LONG).show());
        webView.loadUrl(origin.toString());
    }

    private void finishFileChooser(Uri[] files) {
        if (fileCallback == null) {
            return;
        }
        fileCallback.onReceiveValue(files);
        fileCallback = null;
    }

    @Override
    protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request == PICK_FILE) {
            finishFileChooser(WebChromeClient.FileChooserParams.parseResult(result, data));
        }
    }

    @Override
    public void onBackPressed() {
        if (webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onDestroy() {
        finishFileChooser(null);
        webView.destroy();
        super.onDestroy();
    }
}
