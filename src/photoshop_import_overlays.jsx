#target photoshop

/*
Batch-import generated *_alpha.png files as editable pixel layers and save PSDs.

Run from Photoshop: File > Scripts > Browse...
*/

(function () {
    var oldDialogs = app.displayDialogs;
    var oldRulerUnits = app.preferences.rulerUnits;

    function chooseFolder(promptText) {
        var folder = Folder.selectDialog(promptText);
        if (folder === null) {
            throw new Error("Cancelled.");
        }
        return folder;
    }

    function stemOf(fileName) {
        var dot = fileName.lastIndexOf(".");
        return dot >= 0 ? fileName.substring(0, dot) : fileName;
    }

    function isSourceImage(file) {
        return file instanceof File && /\.(jpe?g|png|tif|tiff)$/i.test(file.name) && !/_alpha\.png$/i.test(file.name);
    }

    function buildOverlayMap(folder) {
        var files = folder.getFiles();
        var result = {};
        var i;
        var match;

        for (i = 0; i < files.length; i += 1) {
            if (!(files[i] instanceof File)) {
                continue;
            }
            match = files[i].name.match(/^(.*)_alpha\.png$/i);
            if (match) {
                result[match[1].toLowerCase()] = files[i];
            }
        }
        return result;
    }

    function closeWithoutSaving(documentRef) {
        if (documentRef) {
            try {
                documentRef.close(SaveOptions.DONOTSAVECHANGES);
            } catch (ignore) {
            }
        }
    }

    function px(unitValue) {
        return Math.round(unitValue.as("px"));
    }

    var sourceFolder;
    var overlayFolder;
    var outputFolder;
    var overwrite;
    var overlayMap;
    var sourceFiles;
    var psdOptions;
    var processed = 0;
    var missing = 0;
    var skippedExisting = 0;
    var failed = [];
    var i;

    try {
        sourceFolder = chooseFolder("Select the folder containing the original images.");
        overlayFolder = chooseFolder("Select the folder containing *_alpha.png overlays.");
        outputFolder = chooseFolder("Select the folder where PSD files will be saved.");
        overwrite = confirm("Overwrite existing PSD files?\n\nYes: overwrite\nNo: skip existing files");

        overlayMap = buildOverlayMap(overlayFolder);
        sourceFiles = sourceFolder.getFiles(isSourceImage);
        sourceFiles.sort(function (a, b) {
            var left = a.name.toLowerCase();
            var right = b.name.toLowerCase();
            return left < right ? -1 : (left > right ? 1 : 0);
        });

        if (sourceFiles.length === 0) {
            alert("No source images were found.");
            return;
        }

        psdOptions = new PhotoshopSaveOptions();
        psdOptions.layers = true;
        psdOptions.embedColorProfile = true;
        psdOptions.maximizeCompatibility = true;

        app.displayDialogs = DialogModes.NO;
        app.preferences.rulerUnits = Units.PIXELS;

        for (i = 0; i < sourceFiles.length; i += 1) {
            var sourceFile = sourceFiles[i];
            var stem = stemOf(sourceFile.name);
            var overlayFile = overlayMap[stem.toLowerCase()];
            var outputFile = new File(outputFolder.fsName + "/" + stem + ".psd");
            var sourceDoc = null;
            var overlayDoc = null;

            if (!overlayFile) {
                missing += 1;
                continue;
            }
            if (outputFile.exists && !overwrite) {
                skippedExisting += 1;
                continue;
            }

            try {
                sourceDoc = app.open(sourceFile);
                overlayDoc = app.open(overlayFile);

                if (px(sourceDoc.width) !== px(overlayDoc.width) || px(sourceDoc.height) !== px(overlayDoc.height)) {
                    throw new Error(
                        "Image size mismatch: original " + px(sourceDoc.width) + "x" + px(sourceDoc.height) +
                        ", overlay " + px(overlayDoc.width) + "x" + px(overlayDoc.height)
                    );
                }

                app.activeDocument = overlayDoc;
                var overlayLayer = overlayDoc.activeLayer;
                var importedLayer = overlayLayer.duplicate(sourceDoc, ElementPlacement.PLACEATBEGINNING);

                app.activeDocument = sourceDoc;
                importedLayer.name = "correction_overlay";
                importedLayer.opacity = 100;
                importedLayer.blendMode = BlendMode.NORMAL;

                if (sourceDoc.layers.length > 1) {
                    sourceDoc.layers[sourceDoc.layers.length - 1].name = "original";
                }

                closeWithoutSaving(overlayDoc);
                overlayDoc = null;

                sourceDoc.saveAs(outputFile, psdOptions, false, Extension.LOWERCASE);
                closeWithoutSaving(sourceDoc);
                sourceDoc = null;
                processed += 1;
            } catch (itemError) {
                failed.push(sourceFile.name + ": " + itemError.message);
                closeWithoutSaving(overlayDoc);
                closeWithoutSaving(sourceDoc);
            }
        }

        var summary =
            "Finished.\n\n" +
            "PSD files created: " + processed + "\n" +
            "Overlay not found: " + missing + "\n" +
            "Existing PSD skipped: " + skippedExisting + "\n" +
            "Errors: " + failed.length;

        if (failed.length > 0) {
            summary += "\n\nFirst errors:\n" + failed.slice(0, 10).join("\n");
        }
        alert(summary);
    } catch (error) {
        if (error.message !== "Cancelled.") {
            alert("Stopped: " + error.message);
        }
    } finally {
        app.displayDialogs = oldDialogs;
        app.preferences.rulerUnits = oldRulerUnits;
    }
}());
