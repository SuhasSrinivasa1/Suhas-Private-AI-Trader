package com.suhas.iposentinel

import android.content.Context
import android.content.Intent
import androidx.core.content.FileProvider
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneOffset
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

object AppAudit {
    private fun auditDir(context: Context): File = File(context.filesDir, "audit")

    fun log(context: Context, eventType: String, payload: JSONObject = JSONObject()) {
        runCatching {
            val dir = auditDir(context)
            dir.mkdirs()
            val day = LocalDate.now(ZoneOffset.UTC).toString()
            val file = File(dir, day + ".jsonl")
            val record = JSONObject()
                .put("timestamp", Instant.now().toString())
                .put("event_type", eventType)
                .put("payload", payload)
            file.appendText(record.toString() + "\n")
        }
    }

    private fun localAudit(context: Context, days: Int): String {
        val dir = auditDir(context)
        if (!dir.exists()) return ""
        val today = LocalDate.now(ZoneOffset.UTC)
        val wanted = (0 until days).map { offset -> today.minusDays(offset.toLong()).toString() }.toSet()
        return dir.listFiles()
            ?.filter { file -> file.extension == "jsonl" && file.nameWithoutExtension in wanted }
            ?.sortedBy { file -> file.name }
            ?.joinToString(separator = "") { file -> file.readText() }
            .orEmpty()
    }

    suspend fun exportWeekly(context: Context): File = withContext(Dispatchers.IO) {
        val backendResult = BackendApi().exportAudit(7)
        val exportDir = File(context.cacheDir, "exports").apply { mkdirs() }
        val safeTime = Instant.now().toString().replace(":", "-")
        val zipFile = File(exportDir, "IPO-Sentinel-Weekly-Audit-" + safeTime + ".zip")

        ZipOutputStream(zipFile.outputStream().buffered()).use { zip ->
            zip.putNextEntry(ZipEntry("app-audit.jsonl"))
            zip.write(localAudit(context, 7).toByteArray())
            zip.closeEntry()

            zip.putNextEntry(ZipEntry("backend-audit.jsonl"))
            val backendText = if (backendResult.ok) {
                backendResult.body
            } else {
                JSONObject()
                    .put("timestamp", Instant.now().toString())
                    .put("event_type", "BACKEND_AUDIT_UNAVAILABLE")
                    .put("error", backendResult.error ?: "unknown")
                    .toString() + "\n"
            }
            zip.write(backendText.toByteArray())
            zip.closeEntry()

            zip.putNextEntry(ZipEntry("metadata.json"))
            val metadata = JSONObject()
                .put("app_version", BuildConfig.VERSION_NAME)
                .put("exported_at", Instant.now().toString())
                .put("period_days", 7)
                .put("backend_audit_included", backendResult.ok)
                .put("note", "Groww TOTP token and secret are never included in audit exports.")
            zip.write(metadata.toString(2).toByteArray())
            zip.closeEntry()
        }

        log(context, "WEEKLY_AUDIT_EXPORTED", JSONObject().put("file_name", zipFile.name))
        zipFile
    }

    fun shareExport(context: Context, file: File) {
        val uri = FileProvider.getUriForFile(
            context,
            BuildConfig.APPLICATION_ID + ".fileprovider",
            file
        )
        val intent = Intent(Intent.ACTION_SEND).apply {
            type = "application/zip"
            putExtra(Intent.EXTRA_STREAM, uri)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        context.startActivity(Intent.createChooser(intent, "Export IPO Sentinel weekly logs"))
    }
}
