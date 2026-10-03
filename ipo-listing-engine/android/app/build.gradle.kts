plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

fun escapedBuildConfig(value: String): String =
    value.replace("\\", "\\\\").replace("\"", "\\\"")

val ipoSentinelApiUrl = System.getenv("IPO_SENTINEL_API_URL") ?: ""
val ipoSentinelDeviceKey = System.getenv("IPO_SENTINEL_DEVICE_KEY") ?: ""

android {
    namespace = "com.suhas.iposentinel"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.suhas.iposentinel"
        minSdk = 28
        targetSdk = 35
        versionCode = 4
        versionName = "0.4.0"

        buildConfigField(
            "String",
            "IPO_SENTINEL_API_URL",
            "\"${escapedBuildConfig(ipoSentinelApiUrl)}\""
        )
        buildConfigField(
            "String",
            "IPO_SENTINEL_DEVICE_KEY",
            "\"${escapedBuildConfig(ipoSentinelDeviceKey)}\""
        )
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions { jvmTarget = "17" }
}

dependencies {
    val bom = platform("androidx.compose:compose-bom:2025.01.01")
    implementation(bom)
    androidTestImplementation(bom)
    implementation("androidx.activity:activity-compose:1.10.0")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    debugImplementation("androidx.compose.ui:ui-tooling")
}
