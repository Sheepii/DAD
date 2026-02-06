(function () {
  function findTemplateForm() {
    return (
      document.querySelector("form#tasktemplate_form") ||
      document.querySelector("form[action*='/tasktemplate/']")
    );
  }

  function getAttachmentFileInputs(form) {
    return Array.from(
      form.querySelectorAll("input[type='file'][name$='attachment_upload']")
    );
  }

  function ensureRowNotice(row) {
    var existing = row.querySelector(".attachment-upload-notice");
    if (existing) {
      return existing;
    }
    var notice = document.createElement("div");
    notice.className = "attachment-upload-notice";
    notice.style.marginTop = "6px";
    notice.style.fontSize = "12px";
    notice.style.opacity = "0.85";
    notice.style.color = "#f0ad4e";
    notice.textContent = "Pending upload. Click Save to upload this file.";
    return notice;
  }

  function setPendingPreview(input) {
    var row = input.closest("tr");
    if (!row) {
      return;
    }
    var previewCell = row.querySelector("td.field-attachment_preview");
    var filenameField = row.querySelector("input[name$='-filename']");
    var driveIdField = row.querySelector("input[name$='-drive_file_id']");
    if (!input.files || !input.files.length) {
      return;
    }
    var file = input.files[0];
    if (filenameField && (!filenameField.value || filenameField.value.trim() === "")) {
      filenameField.value = file.name;
    }
    if (driveIdField) {
      driveIdField.placeholder = "Will be set after Save";
    }
    if (previewCell) {
      var ext = (file.name.split(".").pop() || "").toLowerCase();
      var isImage = file.type.indexOf("image/") === 0;
      var isVideo = file.type.indexOf("video/") === 0;
      var html = "";
      if (isImage) {
        var url = URL.createObjectURL(file);
        html =
          '<img src="' +
          url +
          '" style="width:80px;height:80px;object-fit:cover;border:1px solid #ddd;border-radius:6px;background:#000;" />';
      } else if (isVideo) {
        html =
          '<div style="width:80px;height:80px;border:1px solid #ddd;border-radius:6px;display:flex;align-items:center;justify-content:center;background:#000;color:#fff;font-size:11px;">VIDEO</div>';
      } else {
        html =
          '<div style="width:80px;height:80px;border:1px solid #ddd;border-radius:6px;display:flex;align-items:center;justify-content:center;background:#000;color:#fff;font-size:11px;">' +
          (ext ? ext.toUpperCase() : "FILE") +
          "</div>";
      }
      previewCell.innerHTML = html;
      previewCell.appendChild(ensureRowNotice(row));
    }
  }

  function ensureStatusBanner(form) {
    var existing = document.getElementById("template-upload-status");
    if (existing) {
      return existing;
    }
    var banner = document.createElement("div");
    banner.id = "template-upload-status";
    banner.style.display = "none";
    banner.style.margin = "10px 0";
    banner.style.padding = "10px 12px";
    banner.style.border = "1px solid #2c2c2c";
    banner.style.borderRadius = "8px";
    banner.style.background = "#1c1c1c";
    banner.style.color = "#e2e2e2";
    banner.innerHTML =
      "<strong>Uploading template files...</strong><div style='margin-top:6px;opacity:0.85;'>Please wait. This can take a moment for larger files.</div>";
    form.prepend(banner);
    return banner;
  }

  document.addEventListener("DOMContentLoaded", function () {
    var form = findTemplateForm();
    if (!form) {
      return;
    }

    var banner = ensureStatusBanner(form);
    getAttachmentFileInputs(form).forEach(function (input) {
      input.addEventListener("change", function () {
        setPendingPreview(input);
      });
    });

    form.addEventListener("submit", function () {
      var inputs = getAttachmentFileInputs(form);
      var hasUploads = inputs.some(function (input) {
        return input.files && input.files.length > 0;
      });
      if (!hasUploads) {
        return;
      }
      banner.style.display = "block";
    });
  });
})();
