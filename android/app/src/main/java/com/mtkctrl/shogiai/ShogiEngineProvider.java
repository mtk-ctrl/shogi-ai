package com.mtkctrl.shogiai;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.content.res.AssetFileDescriptor;
import android.content.res.AssetManager;
import android.database.Cursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.util.Log;

import java.io.File;
import java.io.FileNotFoundException;
import java.io.IOException;

public class ShogiEngineProvider extends ContentProvider {
    private static final String TAG = "ShogiEngineProvider";
    private static final String MIME_TYPE = "application/x-shogi-engine";
    private static final String UNSUPPORTED = "Not supported by this provider";

    @Override
    public boolean onCreate() {
        return true;
    }

    @Override
    public AssetFileDescriptor openAssetFile(Uri uri, String mode) throws FileNotFoundException {
        AssetManager manager = getContext().getAssets();
        String fileName = uri.getLastPathSegment();
        if (fileName == null) {
            throw new FileNotFoundException("Missing engine filename");
        }

        try {
            return manager.openFd(fileName);
        } catch (IOException assetError) {
            String libFileName = getContext().getApplicationInfo().nativeLibraryDir
                    + File.separator + fileName;
            try {
                ParcelFileDescriptor pfd = ParcelFileDescriptor.open(
                        new File(libFileName), ParcelFileDescriptor.MODE_READ_ONLY);
                return new AssetFileDescriptor(pfd, 0, AssetFileDescriptor.UNKNOWN_LENGTH);
            } catch (IOException libraryError) {
                Log.e(TAG, "Unable to open engine file: " + libFileName, libraryError);
                throw new FileNotFoundException("Unable to open engine file: " + libFileName);
            }
        }
    }

    @Override
    public String getType(Uri uri) {
        return MIME_TYPE;
    }

    @Override
    public Cursor query(Uri uri, String[] projection, String selection,
                        String[] selectionArgs, String sortOrder) {
        throw new UnsupportedOperationException(UNSUPPORTED);
    }

    @Override
    public Uri insert(Uri uri, ContentValues values) {
        throw new UnsupportedOperationException(UNSUPPORTED);
    }

    @Override
    public int delete(Uri uri, String selection, String[] selectionArgs) {
        throw new UnsupportedOperationException(UNSUPPORTED);
    }

    @Override
    public int update(Uri uri, ContentValues values, String selection,
                      String[] selectionArgs) {
        throw new UnsupportedOperationException(UNSUPPORTED);
    }
}
