plugins {
    id("com.android.application")
}

android {
    namespace = "com.mtkctrl.shogiai"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.mtkctrl.shogiai"
        minSdk = 24
        targetSdk = 36
        versionCode = 14
        versionName = "0.0.13"
    }

    val fixedDevKeystore = file("../signing/dev-signing.p12")
    signingConfigs {
        create("fixedDev") {
            storeFile = fixedDevKeystore
            storePassword = "shogi-ai-dev"
            keyAlias = "shogi-ai-dev"
            keyPassword = "shogi-ai-dev"
            storeType = "PKCS12"
        }
    }

    buildTypes {
        getByName("debug") {
            if (fixedDevKeystore.exists()) {
                signingConfig = signingConfigs.getByName("fixedDev")
            }
        }
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    packaging {
        jniLibs {
            useLegacyPackaging = true
        }
    }
}
