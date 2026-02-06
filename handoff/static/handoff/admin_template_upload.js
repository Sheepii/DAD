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
