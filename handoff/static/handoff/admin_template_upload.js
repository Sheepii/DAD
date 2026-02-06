(function () {
  var activeUploads = 0;

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
    notice.textContent = "Uploading...";
    var uploadCell = row.querySelector("td.field-attachment_upload");
    if (uploadCell) {
      uploadCell.appendChild(notice);
    }
    return notice;
  }

  function getTemplateIdFromPath() {
    var match = window.location.pathname.match(/\/tasktemplate\/(\d+)\/change\/?/);
    return match ? match[1] : "";
  }

  function getUploadUrl() {
    var pathname = window.location.pathname || "";
    var match = pathname.match(/^(.*?\/)handoff\/tasktemplate\//);
    if (match && match[1]) {
      return match[1] + "handoff/template-attachment/upload/";
    }
    return "/admin/handoff/template-attachment/upload/";
  }

  function getCsrfToken(form) {
    var tokenInput = form.querySelector("input[name='csrfmiddlewaretoken']");
    return tokenInput ? tokenInput.value : "";
  }

  function setPreviewCell(previewCell, file, thumbnailUrl) {
    if (!previewCell) {
      return;
    }
    var ext = (file.name.split(".").pop() || "").toLowerCase();
    var isImage = file.type.indexOf("image/") === 0;
    var isVideo = file.type.indexOf("video/") === 0;
    var html = "";
    if (thumbnailUrl) {
      html =
        '<img src="' +
        thumbnailUrl +
        '" style="width:80px;height:80px;object-fit:cover;border:1px solid #ddd;border-radius:6px;background:#000;" />';
    } else if (isImage) {
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
  }

  function setBannerState(banner) {
    if (!banner) {
      return;
    }
    if (activeUploads > 0) {
      banner.style.display = "block";
      banner.style.borderColor = "#2e6da4";
      banner.style.color = "#e6f3ff";
      banner.innerHTML =
        "<strong>Uploading template files...</strong><div style='margin-top:6px;opacity:0.9;'>Please wait until all uploads finish (" +
        activeUploads +
        " active).</div>";
      return;
    }
    banner.style.display = "none";
  }

  function setSaveButtonsDisabled(form, disabled) {
    var saveButtons = form.querySelectorAll("input[name='_save'], input[name='_continue'], input[name='_addanother']");
    saveButtons.forEach(function (btn) {
      btn.disabled = disabled;
    });
  }

  function uploadImmediately(form, input) {
    var row = input.closest("tr");
    if (!row) {
      return;
    }
    if (!input.files || !input.files.length) {
      return;
    }
    var templateId = getTemplateIdFromPath();
    if (!templateId) {
      alert("Save the Task Template first, then upload static files.");
      input.value = "";
      return;
    }

    var file = input.files[0];
    var previewCell = row.querySelector("td.field-attachment_preview");
    var linkCell = row.querySelector("td.field-attachment_link");
    var filenameField = row.querySelector("input[name$='-filename']");
    var driveIdField = row.querySelector("input[name$='-drive_file_id']");
    var uploadCell = row.querySelector("td.field-attachment_upload");
    var banner = document.getElementById("template-upload-status");
    var notice = ensureRowNotice(row);
    setPreviewCell(previewCell, file, "");
    if (filenameField && (!filenameField.value || filenameField.value.trim() === "")) {
      filenameField.value = file.name;
    }
    if (driveIdField) driveIdField.value = "";
    if (linkCell) linkCell.innerHTML = "";

    notice.textContent = "Uploading 0%...";
    notice.style.color = "#f0ad4e";
    if (!notice.parentNode && uploadCell) {
      uploadCell.appendChild(notice);
    } else if (notice.parentNode !== uploadCell && uploadCell) {
      uploadCell.appendChild(notice);
    }

    var data = new FormData();
    data.append("attachment_file", file);
    data.append("template_id", templateId);
    var xhr = new XMLHttpRequest();
    xhr.open("POST", getUploadUrl(), true);
    var csrf = getCsrfToken(form);
    if (csrf) {
      xhr.setRequestHeader("X-CSRFToken", csrf);
    }
    activeUploads += 1;
    setBannerState(banner);
    setSaveButtonsDisabled(form, true);
    xhr.upload.onprogress = function (event) {
      if (!event.lengthComputable) {
        return;
      }
      var percent = Math.round((event.loaded / event.total) * 100);
      notice.textContent = "Uploading " + percent + "%...";
    };
    xhr.onload = function () {
      if (xhr.status < 200 || xhr.status >= 300) {
        var message = "Upload failed.";
        try {
          var badPayload = JSON.parse(xhr.responseText || "{}");
          if (badPayload.error) message = badPayload.error;
        } catch (e) {}
        notice.style.color = "#d9534f";
        notice.textContent = message;
        activeUploads = Math.max(0, activeUploads - 1);
        setBannerState(banner);
        setSaveButtonsDisabled(form, activeUploads > 0);
        return;
      }
      var payload = JSON.parse(xhr.responseText || "{}");
      if (!payload.ok) {
        notice.style.color = "#d9534f";
        notice.textContent = payload.error || "Upload failed.";
        activeUploads = Math.max(0, activeUploads - 1);
        setBannerState(banner);
        setSaveButtonsDisabled(form, activeUploads > 0);
        return;
      }
      if (driveIdField) driveIdField.value = payload.drive_file_id || "";
      if (filenameField) filenameField.value = payload.filename || file.name;
      if (linkCell && payload.open_url) {
        linkCell.innerHTML =
          '<a href="' + payload.open_url + '" target="_blank" rel="noopener">Open file</a>';
      }
      setPreviewCell(previewCell, file, payload.thumbnail_url || "");
      notice.style.color = "#5cb85c";
      notice.textContent = "Uploaded. Click Save to persist this row.";
      input.value = "";
      activeUploads = Math.max(0, activeUploads - 1);
      setBannerState(banner);
      setSaveButtonsDisabled(form, activeUploads > 0);
    };
    xhr.onerror = function () {
      notice.style.color = "#d9534f";
      notice.textContent = "Upload failed.";
      activeUploads = Math.max(0, activeUploads - 1);
      setBannerState(banner);
      setSaveButtonsDisabled(form, activeUploads > 0);
    };
    xhr.send(data);
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
    setBannerState(banner);

    form.addEventListener("change", function (event) {
      var target = event.target;
      if (!target || target.tagName !== "INPUT" || target.type !== "file") {
        return;
      }
      if (!target.name || !target.name.endsWith("attachment_upload")) {
        return;
      }
      uploadImmediately(form, target);
    });

    form.addEventListener("submit", function (event) {
      if (activeUploads <= 0) {
        return;
      }
      window.alert("Please wait for attachment uploads to finish before saving.");
      event.preventDefault();
      banner.style.display = "block";
    });
  });
})();
